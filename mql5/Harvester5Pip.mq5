//+------------------------------------------------------------------+
//|                                               Harvester5Pip.mq5  |
//|                    5-pip grid harvester -- execution engine      |
//|                                                                  |
//|  Implements the blueprint in harvester-blueprint.md:             |
//|    * resting LIMIT ladder for entries (no slippage, server-side) |
//|    * attached LIMIT take-profit  (survives EA death)             |
//|    * attached far SL as disaster backstop (survives EA death)    |
//|    * client-side BASKET STOP on displacement -> market close-all |
//|    * anchor FROZEN on first fill  (see FreezeAnchor notes)       |
//|    * ER regime gate / RSI entry veto / BB-width vol veto         |
//|                                                                  |
//|  LADDER DEPTH = 3 levels. Measured marginal value of each level: |
//|    1->2 +82% income | 2->3 +22% | 3->4 +3.2% | 5th cannot fill   |
//|                                                                  |
//|  Levels are identified by MAGIC NUMBER, not comment, because     |
//|  brokers frequently overwrite comments.                          |
//+------------------------------------------------------------------+
#property copyright "Harvester blueprint reference implementation"
#property link      ""
#property version   "1.00"
#property description "5-pip limit-ladder harvester with basket stop."
#property description "Attach to EUR/USD M15. Test on demo first."

#include <Trade\Trade.mqh>

//====================================================================
//  INPUTS
//====================================================================
input group           "=== Target ==="
input double InpTPPips          = 5.0;    // Take profit (pips) = your 50c target
input double InpLotsPerLevel    = 0.01;   // Lots per level

input group           "=== Ladder geometry ==="
input double InpATRMult         = 2.0;    // Base spacing = ATRMult x ATR
input double InpSpacingMinPips  = 7.0;    // Spacing floor (protects cost ratio)
input double InpSpacingMaxPips  = 15.0;   // Spacing ceiling
input double InpWiden           = 0.25;   // Gap k = s*(1+Widen*(k-1))
input int    InpMaxLevels       = 3;      // Ladder depth (3 = measured optimum)
input int    InpPrePlaceLevels  = 2;      // Pendings resting on server at once

input group           "=== Basket stop ==="
input double InpBasketMult      = 6.0;    // Stop at |price-anchor| > Mult x spacing
input double InpEquityStopPct   = 6.0;    // Also stop at this % of equity lost
input double InpDisasterMult    = 2.0;    // Per-position SL = Mult x D_max
input int    InpCooldownBars    = 96;     // Bars flat after a basket stop

input group           "=== Regime gate / filters ==="
input int    InpAnchorMA        = 20;     // SMA period (anchor + BB basis)
input int    InpATRPeriod       = 20;     // ATR period
input int    InpERWindow        = 20;     // Efficiency Ratio window
input double InpERFull          = 0.35;   // ER below this = full size
input double InpERHalf          = 0.50;   // ER above this = stand down
input int    InpRSIPeriod       = 14;     // RSI period
input double InpRSILongVeto     = 25.0;   // No new longs below this RSI
input double InpRSIShortVeto    = 75.0;   // No new shorts above this RSI
input double InpBWExpansionMult = 1.6;    // Flat if BBwidth > Mult x median
input int    InpBWMedianBars    = 50;     // Lookback for BB width median

input group           "=== Operations ==="
input int    InpRolloverMins    = 5;      // Blackout +/- mins around server 00:00
input bool   InpFlatOnFriday    = true;   // Close all before weekend
input int    InpFridayCloseHour = 20;     // Server hour to flatten Friday
input long   InpMagic           = 770501; // Base magic number
input int    InpSlippagePoints  = 10;     // Max deviation for market exits
input bool   InpVerboseLog      = true;   // Log every cycle event

//====================================================================
//  GLOBALS
//====================================================================
CTrade   trade;

int      hMA = INVALID_HANDLE;
int      hATR = INVALID_HANDLE;
int      hRSI = INVALID_HANDLE;
int      hBands = INVALID_HANDLE;

enum ENUM_HSTATE { HS_FLAT = 0, HS_ACTIVE = 1, HS_COOLDOWN = 2 };

ENUM_HSTATE g_state        = HS_FLAT;
double      g_anchor       = 0.0;   // FROZEN while ACTIVE
double      g_spacing      = 0.0;   // pips, frozen with the anchor
datetime    g_cooldownTill = 0;
datetime    g_lastBarTime  = 0;
double      g_pip          = 0.0;
double      g_cycleStartEq = 0.0;

// persistence keys so state survives terminal restart / recompile
string   gvAnchor, gvSpacing, gvState, gvCooldown;

//====================================================================
//  SMALL HELPERS
//====================================================================
double PipSize()
{
   int d = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   return (d == 3 || d == 5) ? 10.0 * _Point : _Point;
}

double NormPrice(double p)
{
   return NormalizeDouble(p, (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS));
}

double NormVolume(double v)
{
   double mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double st = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(st <= 0.0) st = 0.01;
   v = MathRound(v / st) * st;
   v = MathMax(mn, MathMin(mx, v));
   return NormalizeDouble(v, 2);
}

// ---- magic encoding: base + (100|200) + level -----------------------
long MagicFor(const int side, const int level)
{
   return InpMagic + (side > 0 ? 100 : 200) + level;
}
bool IsOurMagic(const long m)
{
   return (m > InpMagic && m <= InpMagic + 300);
}
int LevelFromMagic(const long m)
{
   return (int)((m - InpMagic) % 100);
}
int SideFromMagic(const long m)
{
   return (((m - InpMagic) / 100) == 1) ? 1 : -1;
}

void Log(const string msg)
{
   if(InpVerboseLog) Print("[HARV] ", msg);
}

//====================================================================
//  LEVEL GEOMETRY
//  depth_k = spacing * SUM_{j=1..k} (1 + Widen*(j-1))
//====================================================================
double LevelDepthPips(const int level, const double spacingPips)
{
   double cum = 0.0;
   for(int k = 1; k <= level; k++)
      cum += spacingPips * (1.0 + InpWiden * (k - 1));
   return cum;
}

double DMaxPips(const double spacingPips)
{
   return InpBasketMult * spacingPips;
}

//====================================================================
//  INDICATOR READS
//====================================================================
bool ReadBuf(const int handle, const int buffer, double &out)
{
   double tmp[];
   if(CopyBuffer(handle, buffer, 0, 1, tmp) < 1) return false;
   out = tmp[0];
   return true;
}

// Efficiency Ratio = |net change| / sum(|bar-to-bar change|)
bool ComputeER(double &er)
{
   int need = InpERWindow + 1;
   double c[];
   ArraySetAsSeries(c, true);
   if(CopyClose(_Symbol, PERIOD_CURRENT, 0, need, c) < need) return false;

   double net  = MathAbs(c[0] - c[InpERWindow]);
   double path = 0.0;
   for(int i = 0; i < InpERWindow; i++)
      path += MathAbs(c[i] - c[i + 1]);

   if(path <= 0.0) return false;
   er = net / path;
   return true;
}

// Median of BB width over the last N bars, in price units
bool ComputeBBWidthMedian(double &widthNow, double &widthMedian)
{
   int n = InpBWMedianBars;
   double up[], lo[];
   ArraySetAsSeries(up, true);
   ArraySetAsSeries(lo, true);
   if(CopyBuffer(hBands, 1, 0, n, up) < n) return false;   // 1 = UPPER
   if(CopyBuffer(hBands, 2, 0, n, lo) < n) return false;   // 2 = LOWER

   double w[];
   ArrayResize(w, n);
   for(int i = 0; i < n; i++) w[i] = up[i] - lo[i];
   widthNow = w[0];

   ArraySort(w);   // ascending
   widthMedian = (n % 2 == 1) ? w[n / 2] : 0.5 * (w[n / 2 - 1] + w[n / 2]);
   return true;
}

//====================================================================
//  GATES
//  returns size multiplier: 1.0 full, 0.5 half, 0.0 stand down
//====================================================================
double SizeMultiplier(double &erOut)
{
   double er;
   if(!ComputeER(er)) { erOut = -1.0; return 0.0; }
   erOut = er;

   double mult = 1.0;
   if(er > InpERHalf)      mult = 0.0;
   else if(er > InpERFull) mult = 0.5;

   double wNow, wMed;
   if(ComputeBBWidthMedian(wNow, wMed) && wMed > 0.0)
      if(wNow > InpBWExpansionMult * wMed) mult = 0.0;   // vol expansion

   return mult;
}

bool InRolloverBlackout()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int mins = dt.hour * 60 + dt.min;
   return (mins < InpRolloverMins) || (mins > (1440 - InpRolloverMins));
}

bool FridayFlattenTime()
{
   if(!InpFlatOnFriday) return false;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   return (dt.day_of_week == 5 && dt.hour >= InpFridayCloseHour);
}

//====================================================================
//  BOOK INSPECTION
//====================================================================
int CountOurPositions()
{
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(!IsOurMagic(PositionGetInteger(POSITION_MAGIC))) continue;
      n++;
   }
   return n;
}

int CountOurPendings()
{
   int n = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong t = OrderGetTicket(i);
      if(t == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      if(!IsOurMagic(OrderGetInteger(ORDER_MAGIC))) continue;
      n++;
   }
   return n;
}

bool LevelHasPosition(const int side, const int level)
{
   long want = MagicFor(side, level);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) == want) return true;
   }
   return false;
}

bool LevelHasPending(const int side, const int level)
{
   long want = MagicFor(side, level);
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong t = OrderGetTicket(i);
      if(t == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      if(OrderGetInteger(ORDER_MAGIC) == want) return true;
   }
   return false;
}

// Deepest level currently holding a position (0 if none), per side
int DeepestFilled(const int side)
{
   int deepest = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      long m = PositionGetInteger(POSITION_MAGIC);
      if(!IsOurMagic(m)) continue;
      if(SideFromMagic(m) != side) continue;
      int lv = LevelFromMagic(m);
      if(lv > deepest) deepest = lv;
   }
   return deepest;
}

double BasketFloatingPL()
{
   double pl = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(!IsOurMagic(PositionGetInteger(POSITION_MAGIC))) continue;
      pl += PositionGetDouble(POSITION_PROFIT)
          + PositionGetDouble(POSITION_SWAP);
   }
   return pl;
}

//====================================================================
//  ORDER ACTIONS
//====================================================================
void CancelAllPendings()
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong t = OrderGetTicket(i);
      if(t == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      if(!IsOurMagic(OrderGetInteger(ORDER_MAGIC))) continue;
      if(!trade.OrderDelete(t))
         Log(StringFormat("OrderDelete failed #%I64u ret=%d", t, trade.ResultRetcode()));
   }
}

void CloseAllPositions(const string reason)
{
   trade.SetDeviationInPoints(InpSlippagePoints);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(!IsOurMagic(PositionGetInteger(POSITION_MAGIC))) continue;
      if(!trade.PositionClose(t))
         Log(StringFormat("PositionClose failed #%I64u ret=%d",
                          t, trade.ResultRetcode()));
   }
   Log("CLOSE ALL -- " + reason);
}

//------------------------------------------------------------------
// Place one pending limit for (side, level). Returns true on success.
//------------------------------------------------------------------
bool PlaceLevel(const int side, const int level, const double sizeMult)
{
   double depth = LevelDepthPips(level, g_spacing);
   double entry = (side > 0) ? g_anchor - depth * g_pip
                             : g_anchor + depth * g_pip;
   entry = NormPrice(entry);

   // A BUY LIMIT must sit BELOW ask, a SELL LIMIT ABOVE bid, by stops level.
   double ask   = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid   = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   long   stopL = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double minD  = (double)stopL * _Point;

   if(side > 0 && entry >= ask - minD) return false;   // not a valid limit yet
   if(side < 0 && entry <= bid + minD) return false;

   double dmax = DMaxPips(g_spacing);
   double tp   = (side > 0) ? entry + InpTPPips * g_pip
                            : entry - InpTPPips * g_pip;
   double sl   = (side > 0) ? entry - InpDisasterMult * dmax * g_pip
                            : entry + InpDisasterMult * dmax * g_pip;

   tp = NormPrice(tp);
   sl = NormPrice(sl);

   double vol = NormVolume(InpLotsPerLevel * sizeMult);
   if(vol <= 0.0) return false;

   trade.SetExpertMagicNumber((ulong)MagicFor(side, level));
   trade.SetDeviationInPoints(InpSlippagePoints);

   bool ok = (side > 0)
      ? trade.BuyLimit (vol, entry, _Symbol, sl, tp, ORDER_TIME_GTC, 0, "harv")
      : trade.SellLimit(vol, entry, _Symbol, sl, tp, ORDER_TIME_GTC, 0, "harv");

   if(ok)
      Log(StringFormat("PLACE %s L%d @ %.5f tp=%.5f sl=%.5f vol=%.2f",
                       (side > 0 ? "BUY" : "SELL"), level, entry, tp, sl, vol));
   else
      Log(StringFormat("PLACE FAILED %s L%d @ %.5f ret=%d",
                       (side > 0 ? "BUY" : "SELL"), level, entry,
                       trade.ResultRetcode()));
   return ok;
}

//------------------------------------------------------------------
// Maintain the sliding pre-place window on both sides.
// NOTE: pre-placing 2-3 levels is an OPERATIONAL control (how many
// pendings sit on the server), NOT the ladder depth. Ladder depth is
// InpMaxLevels. These are different parameters.
//------------------------------------------------------------------
void MaintainLadder(const double sizeMult)
{
   if(sizeMult <= 0.0) return;
   if(InRolloverBlackout()) return;

   int sides[2] = {1, -1};
   for(int s = 0; s < 2; s++)
   {
      int side  = sides[s];
      int from  = DeepestFilled(side) + 1;
      int to    = (int)MathMin((double)(from + InpPrePlaceLevels - 1),
                              (double)InpMaxLevels);

      for(int lv = from; lv <= to; lv++)
      {
         if(LevelHasPosition(side, lv)) continue;
         if(LevelHasPending(side, lv))  continue;
         PlaceLevel(side, lv, sizeMult);
      }
   }
}

//====================================================================
//  STATE PERSISTENCE (survives restart / recompile)
//====================================================================
void SaveState()
{
   GlobalVariableSet(gvAnchor,   g_anchor);
   GlobalVariableSet(gvSpacing,  g_spacing);
   GlobalVariableSet(gvState,    (double)g_state);
   GlobalVariableSet(gvCooldown, (double)g_cooldownTill);
}

void LoadState()
{
   if(GlobalVariableCheck(gvAnchor))   g_anchor  = GlobalVariableGet(gvAnchor);
   if(GlobalVariableCheck(gvSpacing))  g_spacing = GlobalVariableGet(gvSpacing);
   if(GlobalVariableCheck(gvState))    g_state   = (ENUM_HSTATE)(int)GlobalVariableGet(gvState);
   if(GlobalVariableCheck(gvCooldown)) g_cooldownTill = (datetime)GlobalVariableGet(gvCooldown);

   // Reconcile with the actual book -- the book is the truth.
   int nPos = CountOurPositions();
   if(nPos > 0 && (g_anchor <= 0.0 || g_spacing <= 0.0))
   {
      Log("WARNING: positions open but anchor/spacing lost. "
          "Closing basket to restore a known state.");
      CloseAllPositions("state recovery");
      CancelAllPendings();
      g_state = HS_FLAT;
   }
   else if(nPos > 0)
   {
      g_state = HS_ACTIVE;
      Log(StringFormat("Recovered ACTIVE: anchor=%.5f spacing=%.1fp pos=%d",
                       g_anchor, g_spacing, nPos));
   }
   else if(g_state == HS_ACTIVE)
   {
      g_state = HS_FLAT;
   }
}

//====================================================================
//  OnInit
//====================================================================
int OnInit()
{
   g_pip = PipSize();

   gvAnchor   = "HARV_" + _Symbol + "_ANCHOR_"   + (string)InpMagic;
   gvSpacing  = "HARV_" + _Symbol + "_SPACING_"  + (string)InpMagic;
   gvState    = "HARV_" + _Symbol + "_STATE_"    + (string)InpMagic;
   gvCooldown = "HARV_" + _Symbol + "_COOLDOWN_" + (string)InpMagic;

   if(InpMaxLevels < 1 || InpMaxLevels > 8)
   {
      Print("ERROR: InpMaxLevels must be 1..8");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(InpTPPips <= 0.0 || InpSpacingMinPips < InpTPPips)
   {
      Print("ERROR: spacing floor must be >= take profit. "
            "Spacing below TP inflates the tail for no extra income.");
      return INIT_PARAMETERS_INCORRECT;
   }

   // Deepest level must sit well inside the basket stop, or it is decorative.
   double deepest = LevelDepthPips(InpMaxLevels, InpSpacingMinPips);
   double dmax    = DMaxPips(InpSpacingMinPips);
   if(deepest > 0.70 * dmax)
      PrintFormat("WARNING: deepest level %.1fp is %.0f%% of D_max %.1fp. "
                  "Levels beyond ~70%% of D_max rarely fill. "
                  "Reduce InpMaxLevels or raise InpBasketMult.",
                  deepest, 100.0 * deepest / dmax, dmax);

   hMA    = iMA(_Symbol, PERIOD_CURRENT, InpAnchorMA, 0, MODE_SMA, PRICE_CLOSE);
   hATR   = iATR(_Symbol, PERIOD_CURRENT, InpATRPeriod);
   hRSI   = iRSI(_Symbol, PERIOD_CURRENT, InpRSIPeriod, PRICE_CLOSE);
   hBands = iBands(_Symbol, PERIOD_CURRENT, InpAnchorMA, 0, 2.0, PRICE_CLOSE);

   if(hMA == INVALID_HANDLE || hATR == INVALID_HANDLE ||
      hRSI == INVALID_HANDLE || hBands == INVALID_HANDLE)
   {
      Print("ERROR: indicator handle creation failed");
      return INIT_FAILED;
   }

   trade.SetExpertMagicNumber((ulong)InpMagic);
   trade.SetDeviationInPoints(InpSlippagePoints);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetAsyncMode(false);

   LoadState();

   PrintFormat("Harvester5Pip init OK | pip=%.5f | TP=%.1fp | levels=%d | "
               "spacing=[%.1f..%.1f] | D_max=%.1fx | preplace=%d",
               g_pip, InpTPPips, InpMaxLevels, InpSpacingMinPips,
               InpSpacingMaxPips, InpBasketMult, InpPrePlaceLevels);
   PrintFormat("Ladder depths @ spacing 10p: L1=%.1f L2=%.1f L3=%.1f | D_max=%.1f",
               LevelDepthPips(1, 10.0), LevelDepthPips(2, 10.0),
               LevelDepthPips(3, 10.0), DMaxPips(10.0));
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   SaveState();
   if(hMA    != INVALID_HANDLE) IndicatorRelease(hMA);
   if(hATR   != INVALID_HANDLE) IndicatorRelease(hATR);
   if(hRSI   != INVALID_HANDLE) IndicatorRelease(hRSI);
   if(hBands != INVALID_HANDLE) IndicatorRelease(hBands);
   PrintFormat("Harvester5Pip deinit (reason=%d). State saved.", reason);
}

//====================================================================
//  OnTick -- basket monitored EVERY tick, arming only on new bar
//====================================================================
void OnTick()
{
   if((ENUM_SYMBOL_TRADE_MODE)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_MODE)
      == SYMBOL_TRADE_MODE_DISABLED) return;

   // ---------- new-bar detection -----------------------------------
   datetime barT = iTime(_Symbol, PERIOD_CURRENT, 0);
   bool isNewBar = (barT != g_lastBarTime);
   if(isNewBar) g_lastBarTime = barT;

   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(bid <= 0.0 || ask <= 0.0) return;
   double mid = 0.5 * (bid + ask);

   int nPos = CountOurPositions();

   //================================================================
   // 1. FRIDAY FLATTEN  (checked first -- overrides everything)
   //================================================================
   if(FridayFlattenTime())
   {
      if(CountOurPendings() > 0) CancelAllPendings();
      if(nPos > 0) CloseAllPositions("friday flatten");
      g_state  = HS_FLAT;
      g_anchor = 0.0;
      SaveState();
      return;
   }

   //================================================================
   // 2. BASKET STOP -- every tick, before anything else
   //    Primary  : displacement from the FROZEN anchor
   //    Secondary: floating loss as % of equity
   //================================================================
   if(nPos > 0 && g_anchor > 0.0 && g_spacing > 0.0)
   {
      double distPips = MathAbs(mid - g_anchor) / g_pip;
      double dmax     = DMaxPips(g_spacing);
      double floatPL  = BasketFloatingPL();
      double eqTrip   = -(InpEquityStopPct / 100.0)
                        * ((g_cycleStartEq > 0.0) ? g_cycleStartEq
                           : AccountInfoDouble(ACCOUNT_EQUITY));

      bool hitDisp = (distPips > dmax);
      bool hitEq   = (floatPL <= eqTrip);

      if(hitDisp || hitEq)
      {
         Log(StringFormat("BASKET STOP  dist=%.1fp/%.1fp  floatPL=%.2f  "
                          "trip=%.2f  pos=%d  reason=%s",
                          distPips, dmax, floatPL, eqTrip, nPos,
                          hitDisp ? "displacement" : "equity"));
         CancelAllPendings();
         CloseAllPositions(hitDisp ? "basket displacement" : "basket equity");

         g_state        = HS_COOLDOWN;
         g_anchor       = 0.0;
         g_spacing      = 0.0;
         g_cooldownTill = barT + (datetime)(InpCooldownBars *
                          PeriodSeconds(PERIOD_CURRENT));
         SaveState();
         return;
      }
   }

   //================================================================
   // 3. COOLDOWN
   //================================================================
   if(g_state == HS_COOLDOWN)
   {
      if(TimeCurrent() < g_cooldownTill) return;
      g_state = HS_FLAT;
      Log("cooldown finished -> FLAT");
      SaveState();
   }

   //================================================================
   // 4. Book emptied naturally -> release the anchor and re-arm fresh.
   //    Pendings are cancelled too: holding them against a stale anchor
   //    is how a grid ends up laddering around a price that is no
   //    longer the rolling mean.
   //================================================================
   if(g_state == HS_ACTIVE && nPos == 0)
   {
      if(CountOurPendings() > 0) CancelAllPendings();
      g_state  = HS_FLAT;
      g_anchor = 0.0;
      Log("basket closed out -> FLAT (anchor released, will re-arm)");
      SaveState();
   }

   //================================================================
   // 5. Gates (evaluated on bar close to avoid intrabar flip-flop)
   //================================================================
   static double s_sizeMult = 0.0;
   static double s_er = -1.0;
   if(isNewBar || s_er < 0.0)
      s_sizeMult = SizeMultiplier(s_er);

   //================================================================
   // 6. FLAT -> arm.  Anchor is computed ONCE here and then FROZEN.
   //================================================================
   if(g_state == HS_FLAT)
   {
      if(!isNewBar) return;
      if(s_sizeMult <= 0.0) return;
      if(InRolloverBlackout()) return;

      double ma, atr;
      if(!ReadBuf(hMA, 0, ma))  return;
      if(!ReadBuf(hATR, 0, atr)) return;

      double atrPips = atr / g_pip;
      double spacing = InpATRMult * atrPips;
      spacing = MathMax(InpSpacingMinPips, MathMin(InpSpacingMaxPips, spacing));

      g_anchor       = ma;          // <-- frozen from here until flat again
      g_spacing      = spacing;
      g_cycleStartEq = AccountInfoDouble(ACCOUNT_EQUITY);
      g_state        = HS_ACTIVE;

      Log(StringFormat("ARM  anchor=%.5f  spacing=%.1fp  ATR=%.1fp  ER=%.3f  "
                       "size=%.1f  D_max=%.1fp",
                       g_anchor, g_spacing, atrPips, s_er, s_sizeMult,
                       DMaxPips(g_spacing)));
      SaveState();
   }

   //================================================================
   // 7. ACTIVE -> maintain the pre-place window
   //================================================================
   if(g_state == HS_ACTIVE)
   {
      // Stand down: pull pendings but let existing TPs work.
      if(s_sizeMult <= 0.0)
      {
         if(CountOurPendings() > 0)
         {
            CancelAllPendings();
            Log("gate closed (ER/vol) -> pendings cancelled, TPs left live");
         }
         return;
      }

      // RSI veto -- do not deepen the ladder into an impulse.
      double rsiV;
      if(!ReadBuf(hRSI, 0, rsiV)) return;
      bool vetoLong  = (rsiV < InpRSILongVeto);
      bool vetoShort = (rsiV > InpRSIShortVeto);

      if(vetoLong || vetoShort)
      {
         // Remove only the vetoed side's pendings.
         for(int i = OrdersTotal() - 1; i >= 0; i--)
         {
            ulong t = OrderGetTicket(i);
            if(t == 0) continue;
            if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
            long m = OrderGetInteger(ORDER_MAGIC);
            if(!IsOurMagic(m)) continue;
            int sd = SideFromMagic(m);
            if((sd > 0 && vetoLong) || (sd < 0 && vetoShort))
               trade.OrderDelete(t);
         }
         if(vetoLong && vetoShort) return;
      }

      MaintainLadder(s_sizeMult);
   }
}

//====================================================================
//  OnTradeTransaction -- log real fill prices vs requested.
//  This is how you MEASURE limit slippage instead of assuming zero.
//====================================================================
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(trans.symbol != _Symbol) return;

   if(!HistoryDealSelect(trans.deal)) return;
   long magic = HistoryDealGetInteger(trans.deal, DEAL_MAGIC);
   if(!IsOurMagic(magic)) return;

   double dealPrice = HistoryDealGetDouble(trans.deal, DEAL_PRICE);
   long   entryType = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   int    side      = SideFromMagic(magic);
   int    level     = LevelFromMagic(magic);

   if(entryType == DEAL_ENTRY_IN)
   {
      double want = (side > 0)
         ? g_anchor - LevelDepthPips(level, g_spacing) * g_pip
         : g_anchor + LevelDepthPips(level, g_spacing) * g_pip;
      double slipPips = (want > 0.0)
         ? MathAbs(dealPrice - want) / g_pip : 0.0;
      Log(StringFormat("FILL  %s L%d  want=%.5f got=%.5f  slip=%.2fp",
                       (side > 0 ? "BUY" : "SELL"), level, want,
                       dealPrice, slipPips));
   }
   else if(entryType == DEAL_ENTRY_OUT)
   {
      double profit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT);
      Log(StringFormat("EXIT  %s L%d  @ %.5f  profit=%.2f",
                       (side > 0 ? "BUY" : "SELL"), level, dealPrice, profit));
   }
}
//+------------------------------------------------------------------+
