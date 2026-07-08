# -*- coding: utf-8 -*-
"""回调扫描引擎 (PullbackScanner)。

每日扫描自选股列表，识别处于回调买入区的标的。
输出三级分类: READY / WATCH / BLOCKED。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .detector import PullbackDetector
from .schemas import PullbackScanResult, PullbackState, PullbackTier

logger = logging.getLogger(__name__)


@dataclass
class ScanConfig:
    """扫描配置。"""
    symbols: list[str] = field(default_factory=list)       # 要扫描的股票列表
    names: dict[str, str] = field(default_factory=dict)     # symbol → name
    sector_filter: str = ""                                  # 行业过滤 (空白=全扫)
    min_score: float = 50.0                                  # 最低质量分阈值
    require_authentic: bool = True                           # 是否要求通过反操纵验证
    parallel: bool = True                                    # 是否并行扫描


class PullbackScanner:
    """回调扫描引擎。

    用法:
        scanner = PullbackScanner(data_provider, detector)
        result = scanner.scan(ScanConfig(symbols=["000001", "002460"]))
    """

    def __init__(self, data_provider=None, detector: Optional[PullbackDetector] = None):
        """
        Args:
            data_provider: 数据提供者（需有 get_daily_bars 方法）
            detector: PullbackDetector 实例
        """
        self._data = data_provider
        self._detector = detector or PullbackDetector()

    def scan(self, config: ScanConfig) -> PullbackScanResult:
        """执行回调扫描。

        Args:
            config: ScanConfig 扫描配置

        Returns:
            PullbackScanResult with ready/watch/blocked lists
        """
        result = PullbackScanResult(
            scan_time=datetime.now(),
            total_scanned=len(config.symbols),
        )

        for symbol in config.symbols:
            try:
                name = config.names.get(symbol, "")
                state = self._scan_one(symbol, name)

                if state.status.name == "NONE":
                    continue  # 不在回调中，不纳入结果

                # 应用过滤条件
                if state.pullback_score < config.min_score:
                    state.tier = PullbackTier.BLOCKED

                if config.require_authentic and not state.authentic_pullback:
                    state.tier = PullbackTier.BLOCKED

                # 分配到对应列表
                tier = state.tier
                if tier == PullbackTier.READY:
                    result.ready.append(state)
                elif tier == PullbackTier.WATCH:
                    result.watch.append(state)
                else:
                    result.blocked.append(state)

            except Exception as e:
                logger.error("扫描失败 [%s]: %s", symbol, e)
                result.data_gaps.append(f"[{symbol}] {e}")

        # 按回调质量分排序
        result.ready.sort(key=lambda s: s.pullback_score, reverse=True)
        result.watch.sort(key=lambda s: s.pullback_score, reverse=True)
        result.blocked.sort(key=lambda s: s.pullback_score, reverse=True)

        return result

    def _scan_one(self, symbol: str, name: str = "") -> PullbackState:
        """扫描单只股票。"""
        if self._data is None:
            return PullbackState(symbol=symbol, name=name)

        try:
            daily_bars = self._data.get_daily_bars(symbol, count=60)
            if not daily_bars:
                return PullbackState(
                    symbol=symbol, name=name,
                    data_freshness="日线数据获取失败",
                )

            # 尝试获取分钟数据用于操纵检测
            minute_data = None
            try:
                if hasattr(self._data, 'get_minute_bars'):
                    minute_data = self._data.get_minute_bars(symbol)
            except Exception:
                pass

            return self._detector.detect(
                symbol, daily_bars, name=name, minute_data=minute_data,
            )
        except Exception as e:
            logger.warning("单票扫描失败 [%s]: %s", symbol, e)
            return PullbackState(
                symbol=symbol, name=name,
                data_freshness=f"扫描异常: {e}",
            )

    def format_result(self, result: PullbackScanResult) -> str:
        """格式化扫描输出为表格。"""
        lines = [
            f"📊 回调扫描结果 ({result.scan_time.strftime('%Y-%m-%d %H:%M')})",
            f"总计扫描: {result.total_scanned} | "
            f"🟢 可入场: {len(result.ready)} | "
            f"🟡 观察: {len(result.watch)} | "
            f"🔴 禁止: {len(result.blocked)}",
            "",
        ]

        if result.ready:
            lines.append("🟢 回调到位 — 可入场候选:")
            lines.append(f"  {'代码':<8} {'名称':<10} {'评分':>5} {'回落%':>7} {'支撑':>8} {'距支撑%':>7} {'缩量比':>6} {'止跌日':>5}")
            for s in result.ready:
                lines.append(
                    f"  {s.symbol:<8} {s.name:<10} {s.pullback_score:>5.0f} "
                    f"{s.from_high_pct:>6.1f}% {s.nearest_support:>8.2f} "
                    f"{s.support_distance_pct:>6.1f}% {s.volume_shrink_ratio:>5.2f} "
                    f"{s.consecutive_low_stop:>5}"
                )

        if result.watch:
            lines.append("\n🟡 接近回调位 — 继续观察:")
            for s in result.watch[:10]:  # top 10
                lines.append(
                    f"  {s.symbol} {s.name}: {s.entry_condition} "
                    f"(评分 {s.pullback_score:.0f})"
                )

        if result.blocked:
            lines.append(f"\n🔴 已排除: {len(result.blocked)} 支")
            # 只展示有操纵信号的
            traps = [s for s in result.blocked if s.status.value == "PULLBACK_TRAP"]
            if traps:
                lines.append("  操纵陷阱:")
                for s in traps[:5]:
                    lines.append(f"  {s.symbol} {s.name}: {s.entry_condition}")

        if result.data_gaps:
            lines.append(f"\n⚠️ 数据缺口: {len(result.data_gaps)}")
            for gap in result.data_gaps[:5]:
                lines.append(f"  {gap}")

        return "\n".join(lines)
