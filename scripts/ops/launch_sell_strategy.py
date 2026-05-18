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
    sell_low_pct: Decimal = Decimal("30")
    sell_high_pct: Decimal = Decimal("50")
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


@dataclass(frozen=True)
class LargeBuySignal:
    tx_hash: str
    timestamp: int
    spent_v: Decimal | None = None
    spent_usd: Decimal | None = None


@dataclass(frozen=True)
class CustomSellCondition:
    type: str
    price_threshold: Decimal | None = None
    price_unit: str = "usd"
    large_buy_threshold: Decimal | None = None
    large_buy_unit: str = "v"
    roi_threshold_pct: Decimal | None = None


@dataclass(frozen=True)
class CustomSellRule:
    id: str
    type: str
    enabled: bool = False
    sell_pct: Decimal = PCT_0
    operator: str = "and"
    conditions: tuple[CustomSellCondition, ...] = ()
    price_threshold: Decimal | None = None
    price_unit: str = "usd"
    large_buy_threshold: Decimal | None = None
    large_buy_unit: str = "v"
    roi_threshold_pct: Decimal | None = None
    label: str = ""


@dataclass(frozen=True)
class CustomSellConfig:
    name: str = "custom_multi_sell"
    max_tax_rate: Decimal = Decimal("30")
    cooldown_sec: int = 60
    rules: tuple[CustomSellRule, ...] = ()


@dataclass
class MultiSellState:
    total_position_raw: int
    current_balance_raw: int
    total_sold_pct: Decimal = PCT_0
    rule_sold_pct: dict[str, Decimal] = field(default_factory=dict)
    cooldown_until: int = 0
    processed_rule_buy_txs: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class MultiSellInput:
    timestamp: int
    tax_rate: Decimal | None
    current_roi_pct: Decimal | None
    token_price_usd: Decimal | None
    token_price_v: Decimal | None
    recent_large_buys: tuple[LargeBuySignal, ...] = ()


@dataclass(frozen=True)
class RuleSellDelta:
    rule_id: str
    rule_type: str
    label: str
    sell_pct: Decimal
    reason: str
    large_buy_tx_hash: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ruleId": self.rule_id,
            "ruleType": self.rule_type,
            "label": self.label,
            "sellPct": str(self.sell_pct),
            "reason": self.reason,
            "largeBuyTxHash": self.large_buy_tx_hash,
        }


@dataclass(frozen=True)
class MultiSellDecision:
    action: str
    reason: str
    total_sell_pct: Decimal
    amount_raw: int
    rule_deltas: tuple[RuleSellDelta, ...] = ()
    requested_total_sell_pct: Decimal | None = None

    @property
    def should_sell(self) -> bool:
        return self.action == "sell" and self.amount_raw > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "totalSellPct": str(self.total_sell_pct),
            "requestedTotalSellPct": str(self.requested_total_sell_pct or self.total_sell_pct),
            "amountRaw": str(self.amount_raw),
            "ruleDeltas": [item.as_dict() for item in self.rule_deltas],
            "triggerReasons": [item.reason for item in self.rule_deltas],
            "largeBuyTxHash": next((item.large_buy_tx_hash for item in self.rule_deltas if item.large_buy_tx_hash), None),
        }


def roi_target_pct(roi_pct: Decimal | None, config: DualSellConfig = DualSellConfig()) -> Decimal:
    if roi_pct is None:
        return PCT_0
    if roi_pct >= config.roi_high_pct:
        return clamp_pct(config.sell_high_pct)
    if roi_pct >= config.roi_low_pct:
        return clamp_pct(config.sell_low_pct)
    return PCT_0


def large_buy_target_pct(latest_buy_v: Decimal | None, config: DualSellConfig = DualSellConfig()) -> Decimal:
    if latest_buy_v is None:
        return PCT_0
    if latest_buy_v >= config.large_buy_high_v:
        return clamp_pct(config.sell_high_pct)
    if latest_buy_v >= config.large_buy_low_v:
        return clamp_pct(config.sell_low_pct)
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


def _hold_multi(reason: str) -> MultiSellDecision:
    return MultiSellDecision(action="hold", reason=reason, total_sell_pct=PCT_0, amount_raw=0)


def _rule_key(rule_id: str, tx_hash: str | None) -> str:
    return f"{rule_id}:{str(tx_hash or '').lower()}"


def _large_buy_value(event: LargeBuySignal, unit: str) -> Decimal | None:
    normalized = str(unit or "v").strip().lower()
    if normalized == "usd":
        return event.spent_usd
    return event.spent_v


def _qualifying_large_buy_for_threshold(
    *,
    rule_id: str,
    threshold: Decimal | None,
    unit: str,
    signal: MultiSellInput,
    state: MultiSellState,
) -> LargeBuySignal | None:
    if threshold is None or threshold <= 0:
        return None
    candidates: list[tuple[Decimal, LargeBuySignal]] = []
    for event in signal.recent_large_buys:
        if not event.tx_hash:
            continue
        if _rule_key(rule_id, event.tx_hash) in state.processed_rule_buy_txs:
            continue
        value = _large_buy_value(event, unit)
        if value is not None and value >= threshold:
            candidates.append((value, event))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1].timestamp))[1]


def _qualifying_large_buy(
    rule: CustomSellRule,
    signal: MultiSellInput,
    state: MultiSellState,
) -> LargeBuySignal | None:
    return _qualifying_large_buy_for_threshold(
        rule_id=rule.id,
        threshold=rule.large_buy_threshold,
        unit=rule.large_buy_unit,
        signal=signal,
        state=state,
    )


def _price_value(rule: CustomSellRule, signal: MultiSellInput) -> Decimal | None:
    unit = str(rule.price_unit or "usd").strip().lower()
    if unit == "v":
        return signal.token_price_v
    return signal.token_price_usd


def _condition_price_value(condition: CustomSellCondition, signal: MultiSellInput) -> Decimal | None:
    unit = str(condition.price_unit or "usd").strip().lower()
    if unit == "v":
        return signal.token_price_v
    return signal.token_price_usd


def _legacy_conditions(rule: CustomSellRule) -> tuple[CustomSellCondition, ...]:
    if rule.conditions:
        return rule.conditions
    if rule.type == "limit_price":
        return (
            CustomSellCondition(
                type="price",
                price_threshold=rule.price_threshold,
                price_unit=rule.price_unit,
            ),
        )
    if rule.type == "large_buy":
        return (
            CustomSellCondition(
                type="large_buy",
                large_buy_threshold=rule.large_buy_threshold,
                large_buy_unit=rule.large_buy_unit,
            ),
        )
    if rule.type == "high_roi":
        return (
            CustomSellCondition(
                type="roi",
                roi_threshold_pct=rule.roi_threshold_pct,
            ),
        )
    if rule.type == "roi_and_large_buy":
        return (
            CustomSellCondition(type="roi", roi_threshold_pct=rule.roi_threshold_pct),
            CustomSellCondition(
                type="large_buy",
                large_buy_threshold=rule.large_buy_threshold,
                large_buy_unit=rule.large_buy_unit,
            ),
        )
    return ()


def _evaluate_condition(
    *,
    rule: CustomSellRule,
    condition: CustomSellCondition,
    signal: MultiSellInput,
    state: MultiSellState,
) -> tuple[bool, str, str | None]:
    if condition.type == "price":
        price = _condition_price_value(condition, signal)
        if condition.price_threshold is None or price is None or price < condition.price_threshold:
            return False, "", None
        return True, "价格达到", None
    if condition.type == "large_buy":
        event = _qualifying_large_buy_for_threshold(
            rule_id=rule.id,
            threshold=condition.large_buy_threshold,
            unit=condition.large_buy_unit,
            signal=signal,
            state=state,
        )
        if event is None:
            return False, "", None
        return True, "大单达到", event.tx_hash
    if condition.type == "roi":
        if (
            condition.roi_threshold_pct is None
            or signal.current_roi_pct is None
            or signal.current_roi_pct < condition.roi_threshold_pct
        ):
            return False, "", None
        return True, "收益率达到", None
    return False, "", None


def _evaluate_rule_conditions(
    *,
    rule: CustomSellRule,
    signal: MultiSellInput,
    state: MultiSellState,
) -> tuple[bool, str, str | None]:
    conditions = _legacy_conditions(rule)
    if not conditions:
        return False, "", None
    results = [
        _evaluate_condition(rule=rule, condition=condition, signal=signal, state=state)
        for condition in conditions
    ]
    operator = str(rule.operator or "and").strip().lower()
    if operator == "or":
        matched = [item for item in results if item[0]]
        if not matched:
            return False, "", None
        reasons = [item[1] for item in matched if item[1]]
        large_buy_tx = next((item[2] for item in matched if item[2]), None)
        return True, " 或 ".join(reasons) if reasons else "任一条件达到", large_buy_tx

    if not all(item[0] for item in results):
        return False, "", None
    reasons = [item[1] for item in results if item[1]]
    large_buy_tx = next((item[2] for item in results if item[2]), None)
    return True, " 且 ".join(reasons) if reasons else "全部条件达到", large_buy_tx


def evaluate_custom_sell(
    *,
    state: MultiSellState,
    signal: MultiSellInput,
    config: CustomSellConfig,
) -> MultiSellDecision:
    if state.total_position_raw <= 0 or state.current_balance_raw <= 0:
        return _hold_multi("no_position")
    if signal.tax_rate is None or signal.tax_rate > config.max_tax_rate:
        return _hold_multi("tax_not_in_sell_window")
    if signal.timestamp < state.cooldown_until:
        return _hold_multi("cooldown")

    deltas: list[RuleSellDelta] = []
    for rule in config.rules:
        if not rule.enabled:
            continue
        if rule.sell_pct <= 0:
            continue
        sold_for_rule = clamp_pct(state.rule_sold_pct.get(rule.id, PCT_0))
        target = clamp_pct(rule.sell_pct)
        if target <= sold_for_rule:
            continue

        matched, reason, large_buy_tx = _evaluate_rule_conditions(rule=rule, signal=signal, state=state)
        if not matched:
            continue

        delta = clamp_pct(target - sold_for_rule)
        if delta <= 0:
            continue
        deltas.append(
            RuleSellDelta(
                rule_id=rule.id,
                rule_type=rule.type,
                label=rule.label or rule.id,
                sell_pct=delta,
                reason=reason,
                large_buy_tx_hash=large_buy_tx,
            )
        )

    if not deltas:
        return _hold_multi("no_rule_triggered")

    remaining_pct = clamp_pct(PCT_100 - clamp_pct(state.total_sold_pct))
    if remaining_pct <= 0:
        return _hold_multi("target_already_sold")

    allocated: list[RuleSellDelta] = []
    requested_total = PCT_0
    left = remaining_pct
    for item in deltas:
        if left <= 0:
            break
        applied = min(item.sell_pct, left)
        requested_total += item.sell_pct
        if applied > 0:
            allocated.append(
                RuleSellDelta(
                    rule_id=item.rule_id,
                    rule_type=item.rule_type,
                    label=item.label,
                    sell_pct=applied,
                    reason=item.reason,
                    large_buy_tx_hash=item.large_buy_tx_hash,
                )
            )
            left -= applied

    total_delta = sum((item.sell_pct for item in allocated), PCT_0)
    amount_raw = min(
        amount_for_original_position_pct(state.total_position_raw, total_delta),
        int(state.current_balance_raw),
    )
    if amount_raw <= 0:
        return _hold_multi("zero_sell_amount")

    actual_pct = Decimal(amount_raw) * PCT_100 / Decimal(state.total_position_raw)
    if actual_pct < total_delta and total_delta > 0:
        ratio = actual_pct / total_delta
        allocated = [
            RuleSellDelta(
                rule_id=item.rule_id,
                rule_type=item.rule_type,
                label=item.label,
                sell_pct=item.sell_pct * ratio,
                reason=item.reason,
                large_buy_tx_hash=item.large_buy_tx_hash,
            )
            for item in allocated
        ]
        total_delta = actual_pct

    return MultiSellDecision(
        action="sell",
        reason="custom_sell_rules_triggered",
        total_sell_pct=total_delta,
        amount_raw=amount_raw,
        rule_deltas=tuple(allocated),
        requested_total_sell_pct=requested_total,
    )


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
