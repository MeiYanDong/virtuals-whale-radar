#!/usr/bin/env python3
"""Pure confirmed large-buy sell strategy for Virtuals launch positions.

The strategy is intentionally side-effect free. It only decides how much of the
original position should be sold; callers are responsible for simulation,
broadcasting, and state persistence after a successful receipt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_FLOOR
from typing import Any


PCT_0 = Decimal("0")
PCT_30 = Decimal("30")
PCT_50 = Decimal("50")
PCT_100 = Decimal("100")


@dataclass(frozen=True)
class DualSellConfig:
    name: str = "dual_roi_large_buy_sell"
    max_tax_rate: Decimal = Decimal("30")
    roi_low_pct: Decimal = Decimal("30")
    roi_high_pct: Decimal = Decimal("50")
    large_buy_low_v: Decimal = Decimal("5000")
    large_buy_high_v: Decimal = Decimal("8000")
    cooldown_sec: int = 60


@dataclass
class DualSellState:
    total_position_raw: int
    roi_sold_pct: Decimal = PCT_0
    large_buy_sold_pct: Decimal = PCT_0
    cooldown_until: int = 0
    processed_large_buy_txs: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class DualSellInput:
    timestamp: int
    tax_rate: Decimal | None
    current_roi_pct: Decimal | None
    current_balance_raw: int
    latest_buy_v: Decimal | None = None
    latest_buy_tx_hash: str | None = None


@dataclass(frozen=True)
class DualSellDecision:
    action: str
    reason: str
    roi_target_pct: Decimal
    large_buy_target_pct: Decimal
    roi_delta_pct: Decimal
    large_buy_delta_pct: Decimal
    total_sell_pct: Decimal
    amount_raw: int
    requested_total_sell_pct: Decimal | None = None
    trigger_reasons: tuple[str, ...] = ()
    large_buy_tx_hash: str | None = None

    @property
    def should_sell(self) -> bool:
        return self.action == "sell" and self.amount_raw > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "roiTargetPct": str(self.roi_target_pct),
            "largeBuyTargetPct": str(self.large_buy_target_pct),
            "roiDeltaPct": str(self.roi_delta_pct),
            "largeBuyDeltaPct": str(self.large_buy_delta_pct),
            "totalSellPct": str(self.total_sell_pct),
            "requestedTotalSellPct": str(self.requested_total_sell_pct or self.total_sell_pct),
            "amountRaw": str(self.amount_raw),
            "triggerReasons": list(self.trigger_reasons),
            "largeBuyTxHash": self.large_buy_tx_hash,
        }


def roi_target_pct(roi_pct: Decimal | None, config: DualSellConfig = DualSellConfig()) -> Decimal:
    if roi_pct is None:
        return PCT_0
    if roi_pct >= config.roi_high_pct:
        return PCT_50
    if roi_pct >= config.roi_low_pct:
        return PCT_30
    return PCT_0


def large_buy_target_pct(latest_buy_v: Decimal | None, config: DualSellConfig = DualSellConfig()) -> Decimal:
    if latest_buy_v is None:
        return PCT_0
    if latest_buy_v >= config.large_buy_high_v:
        return PCT_50
    if latest_buy_v >= config.large_buy_low_v:
        return PCT_30
    return PCT_0


def clamp_pct(value: Decimal) -> Decimal:
    if value < PCT_0:
        return PCT_0
    if value > PCT_100:
        return PCT_100
    return value


def amount_for_original_position_pct(total_position_raw: int, sell_pct: Decimal) -> int:
    if total_position_raw <= 0 or sell_pct <= 0:
        return 0
    value = Decimal(total_position_raw) * sell_pct / PCT_100
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def evaluate_dual_sell(
    *,
    state: DualSellState,
    signal: DualSellInput,
    config: DualSellConfig = DualSellConfig(),
) -> DualSellDecision:
    def hold(reason: str) -> DualSellDecision:
        return DualSellDecision(
            action="hold",
            reason=reason,
            roi_target_pct=PCT_0,
            large_buy_target_pct=PCT_0,
            roi_delta_pct=PCT_0,
            large_buy_delta_pct=PCT_0,
            total_sell_pct=PCT_0,
            amount_raw=0,
        )

    if state.total_position_raw <= 0 or signal.current_balance_raw <= 0:
        return hold("no_position")
    if signal.tax_rate is None or signal.tax_rate > config.max_tax_rate:
        return hold("tax_not_in_sell_window")
    if signal.timestamp < state.cooldown_until:
        return hold("cooldown")

    roi_target = roi_target_pct(signal.current_roi_pct, config)
    large_target = PCT_0
    large_tx = signal.latest_buy_tx_hash
    if large_tx is None or large_tx not in state.processed_large_buy_txs:
        large_target = large_buy_target_pct(signal.latest_buy_v, config)

    confirmed_target = min(roi_target, large_target)
    already_sold_pct = clamp_pct(state.roi_sold_pct + state.large_buy_sold_pct)
    roi_delta = PCT_0
    if confirmed_target <= 0:
        return DualSellDecision(
            action="hold",
            reason="large_buy_roi_not_confirmed",
            roi_target_pct=roi_target,
            large_buy_target_pct=large_target,
            roi_delta_pct=PCT_0,
            large_buy_delta_pct=PCT_0,
            total_sell_pct=PCT_0,
            amount_raw=0,
            requested_total_sell_pct=PCT_0,
            trigger_reasons=(),
            large_buy_tx_hash=large_tx if large_target > 0 else None,
        )
    large_delta = clamp_pct(confirmed_target - already_sold_pct)
    requested_total_delta = large_delta
    if requested_total_delta <= 0:
        return DualSellDecision(
            action="hold",
            reason="target_already_sold",
            roi_target_pct=roi_target,
            large_buy_target_pct=large_target,
            roi_delta_pct=roi_delta,
            large_buy_delta_pct=large_delta,
            total_sell_pct=PCT_0,
            amount_raw=0,
            requested_total_sell_pct=PCT_0,
            trigger_reasons=(),
            large_buy_tx_hash=large_tx if large_target > 0 else None,
        )

    requested_amount_raw = amount_for_original_position_pct(state.total_position_raw, requested_total_delta)
    amount_raw = min(requested_amount_raw, int(signal.current_balance_raw))
    if amount_raw <= 0:
        return DualSellDecision(
            action="hold",
            reason="zero_sell_amount",
            roi_target_pct=roi_target,
            large_buy_target_pct=large_target,
            roi_delta_pct=roi_delta,
            large_buy_delta_pct=large_delta,
            total_sell_pct=PCT_0,
            amount_raw=0,
            requested_total_sell_pct=requested_total_delta,
            trigger_reasons=(),
            large_buy_tx_hash=large_tx,
        )
    total_delta = Decimal(amount_raw) * PCT_100 / Decimal(state.total_position_raw)
    if requested_amount_raw > amount_raw and requested_total_delta > 0:
        ratio = total_delta / requested_total_delta
        large_delta *= ratio
        total_delta = large_delta

    reasons: list[str] = []
    if large_delta > 0:
        reasons.append("大额买入且收益率达标")
    return DualSellDecision(
        action="sell",
        reason="dual_sell_target_increased",
        roi_target_pct=roi_target,
        large_buy_target_pct=large_target,
        roi_delta_pct=roi_delta,
        large_buy_delta_pct=large_delta,
        total_sell_pct=total_delta,
        amount_raw=amount_raw,
        requested_total_sell_pct=requested_total_delta,
        trigger_reasons=tuple(reasons),
        large_buy_tx_hash=large_tx if large_delta > 0 else None,
    )


def apply_successful_sell(
    *,
    state: DualSellState,
    decision: DualSellDecision,
    timestamp: int,
    config: DualSellConfig = DualSellConfig(),
) -> None:
    if not decision.should_sell:
        return
    state.roi_sold_pct = clamp_pct(state.roi_sold_pct + decision.roi_delta_pct)
    state.large_buy_sold_pct = clamp_pct(state.large_buy_sold_pct + decision.large_buy_delta_pct)
    state.cooldown_until = int(timestamp) + int(config.cooldown_sec)
    if decision.large_buy_tx_hash:
        state.processed_large_buy_txs.add(decision.large_buy_tx_hash)
