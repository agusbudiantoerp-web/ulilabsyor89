"""Portfolio-level exposure checks and indicative position sizing."""
from __future__ import annotations
from daily_signal_risk import build_trade_plan
def allocate_candidates(candidates: list[dict], portfolio_value: float,
                        risk_pct: float=1.0, max_total_exposure_pct: float=60.0,
                        max_single_position_pct: float=15.0, max_positions: int=8) -> dict:
    if portfolio_value<=0 or not 0<risk_pct<=5 or not 0<max_total_exposure_pct<=100:
        raise ValueError("Parameter portofolio tidak valid.")
    selected=[]; skipped=[]; used=0.0
    for item in sorted(candidates,key=lambda x:x.get("score",0),reverse=True):
        if item.get("signal")!="BUY_CANDIDATE": continue
        if len(selected)>=max_positions:
            skipped.append({"ticker":item.get("ticker"),"reason":"Batas jumlah posisi tercapai."}); continue
        plan=build_trade_plan(float(item["close"]),float(item["atr14"]),portfolio_value,
          risk_pct=risk_pct,max_position_pct=max_single_position_pct)
        remaining=portfolio_value*max_total_exposure_pct/100-used
        allowed=int(max(0,remaining)/float(item["close"]))
        market = str(item.get("market", "IDX")).upper()
        lot_size = 100 if market == "IDX" else 1
        raw_shares = min(plan["shares"], allowed)
        plan["shares"] = (raw_shares // lot_size) * lot_size
        plan["lots"] = plan["shares"] // lot_size if market == "IDX" else plan["shares"]
        plan["lot_size"] = lot_size
        plan["position_value"]=plan["shares"]*float(item["close"])
        plan["planned_loss"]=plan["shares"]*plan["risk_per_share"]
        plan["portfolio_weight_pct"]=plan["position_value"]/portfolio_value*100
        if plan["shares"]<=0:
            skipped.append({"ticker":item.get("ticker"),"reason":"Tidak ada kapasitas exposure tersisa."}); continue
        selected.append({"market":item.get("market"),"ticker":item.get("ticker"),"score":item.get("score"),"plan":plan})
        used+=plan["position_value"]
    return {"portfolio_value":portfolio_value,"allocated_value":used,
      "exposure_pct":used/portfolio_value*100,"positions":selected,"skipped":skipped,
      "disclaimer":"Sizing indikatif. Perhitungkan lot size IDX, biaya, likuiditas, korelasi dan posisi aktual sebelum keputusan."}
