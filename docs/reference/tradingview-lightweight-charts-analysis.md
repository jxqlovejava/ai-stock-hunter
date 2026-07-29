# TradingView Lightweight Charts™ — K 线图组件参考分析

> 源码：https://github.com/tradingview/lightweight-charts  
> 定位：轻量级高性能金融 HTML5 K 线图库（TypeScript / Canvas 2D）  
> 许可证：Apache 2.0  
> 分析日期：2026-07-26  
> 相关产品：TradingView Charting Library（完整版，商用）

Lightweight Charts™ 是 TradingView 出品的开源轻量级金融图表库，也是市面上最广泛使用的 A 股/美股 K 线图表组件。其核心架构是一个 TypeScript 编写的 Canvas 2D 渲染引擎，把数据处理、坐标映射、渲染管线、交互响应、插件扩展拆为独立层。与白泽当前纯 CLI 输出（文字/表格）不同，lightweight-charts 提供了**从数据到可视化的一整套映射模型**——白泽如果未来要添加 Web 前端展示层，可以直接借鉴其数据模型、Scale 映射体系和插件渲染管线。

---

## 一、架构全景

```
┌─────────────────────────────────────────────────────┐
│                      API Layer                       │
│  createChart() → IChartApi                          │
│    ├── addSeries(CandleStickSeries) → ISeriesApi    │
│    ├── timeScale() → ITimeScaleApi                  │
│    └── priceScale() → IPriceScaleApi                │
├─────────────────────────────────────────────────────┤
│                     Model Layer                      │
│  ChartModel ─── Pane[] ─── Series[]                 │
│       │                │                            │
│       │          PriceScale / TimeScale              │
│       │                │                            │
│       └── Crosshair / Grid / DataLayer              │
├─────────────────────────────────────────────────────┤
│                    View Layer                        │
│  PaneView / SeriesPaneView / CrosshairPaneView      │
│  PriceAxisView / TimeAxisView                       │
├─────────────────────────────────────────────────────┤
│                  Renderer Layer                      │
│  CandlesticksRenderer / LineRenderer / AreaRenderer │
│  CrosshairRenderer / GridRenderer / AxisRenderer    │
│  CompositeRenderer (merge multiple renderers)        │
├─────────────────────────────────────────────────────┤
│                  Plugin Layer                        │
│  ISeriesPrimitive / IPanePrimitive ─── CustomRender │
│  Built-in: SeriesMarkers / Watermark / WatermarkImg │
└─────────────────────────────────────────────────────┘
```

| 层 | 职责 | 关键文件 |
|----|------|---------|
| **API** | 对外暴露的接口（createChart/addSeries/setData） | `src/api/chart-api.ts`, `src/api/series-api.ts` |
| **Model** | 数据结构与业务逻辑（K 线/Series/Scale/Crosshair） | `src/model/chart-model.ts`, `src/model/series.ts`, `src/model/time-scale.ts` |
| **View** | Model → 渲染数据转换（坐标映射、颜色计算） | `src/model/series/candlesticks-pane-view.ts` |
| **Renderer** | Canvas 2D 绘制（实际画图） | `src/renderers/candlesticks-renderer.ts` |
| **Plugin** | 自定义扩展接口 | `src/plugins/types.ts`, `src/plugins/primitive-wrapper.ts` |
| **GUI** | DOM 绑定、事件处理、Widget 管理 | `src/gui/chart-widget.ts`, `src/gui/mouse-event-handler.ts` |

---

## 二、核心设计模式

### 2.1 Model / View / Renderer 三层分离

这是最核心的架构设计。不同于常见的前端图表库将数据和绘制混在一起，lightweight-charts 做了严格的职责分离：

```
Model (数据 + 业务逻辑)            View (坐标映射 + 颜色计算)          Renderer (Canvas 绘制)
────────────────────              ─────────────────────             ─────────────────────
Bar {time,open,high,low,close}    candlesticksPaneView               CandlesticksRenderer
Series {bars[], options}          → 将 Model 的 OHLC 值               → Canvas 2D:
  ↓ invalidate()                    映射为 Canvas 坐标                  rect(bearX, yTop, w, h)
Pane {priceScale, timeScale}       计算涨跌颜色                       绘制影线
  ↓ invalidate()                 判断实心/空心
```

**关键接口**：

```typescript
// Model → View（数据驱动视图更新）
class Series<T> {
  bars(): Bar[]             // 原始数据
  options(): SeriesOptions  // 样式配置
  paneView(): IPaneView     // 返回对应的 View
}

// View → Renderer（坐标映射后的绘制指令）
interface IPaneView {
  renderer(): IPaneRenderer | null  // 返回渲染器
}

// Renderer（无状态绘制）
interface IPaneRenderer {
  draw(target: CanvasRenderingContext2D, ...): void
}
```

这种设计的优势：
- **可测试性**：Renderer 是纯函数，Model 是纯数据，View 是纯映射，各自可独立测试
- **批量重绘**：`invalidate()` 标记脏区域，下一帧批量重绘，减少 Canvas 重绘次数
- **插件扩展**：自定义 Series 只需实现 `ICustomSeriesPaneView` → 提供自己的 Renderer

### 2.2 Scale 坐标映射体系

TimeScale 和 PriceScale 是坐标映射的枢纽：

```
数据域 (Domain) → 屏幕域 (Range)
  time/price          x/y pixel

TimeScale:
  - HorzScaleBehavior（可替换，支持 time-based 或 index-based 两种模式）
  - tickMarkFormatter（自定义刻度标签格式）
  - visibleRange（当前可视区 [start, end]）
  - barSpacing / rightOffset / scrollPosition

PriceScale:
  - autoScale / logarithmic / percentage / indexedTo100
  - priceRange（当前可视区 [low, high]）
  - invertScale（上下翻转，适用于 RSI 等指标在下方显示）
  - mode（normal / percentage / logarithmic / indexedTo100 / custom）
```

白泽当前的因子计算/诊断结果可以用同样模式映射到可视化坐标——如多维诊断的 6 维雷达图坐标映射、Alpha Lens 的 3D 坐标映射。

### 2.3 插件系统（Primitive API）

v5 引入的插件接口是最值得借鉴的设计。定义两种 Primitive：

```typescript
// 绑定 Series 的插件（技术指标附在特定 Series 上）
interface ISeriesPrimitive<TSeriesType> {
  paneView(): ISeriesPrimitivePaneView | null  // 绘制在 Chart Pane 上
  priceAxisViews(): IPriceAxisView[]           // 绘制在价格轴上
  timeAxisViews(): ITimeAxisView[]             // 绘制在时间轴上
  updateAllViews(): void                        // 数据变化时更新视图
  dataUpdated?(): void                          // Series 数据变更通知
  requestedImageData?(): ImageData              // 大图导出
}

// 绑定 Pane 的插件（全局绘制工具如水印）
interface IPanePrimitive {
  paneView(): IPanePrimitivePaneView | null
  updateAllViews(): void
}
```

插件生命周期：
1. `chart.addSeries(CandlestickSeries)` → 返回 `ISeriesApi`
2. `series.attachPrimitive(myIndicator)` → 绑定自定义指标
3. `myIndicator.paneView()` → 返回 `ISeriesPrimitivePaneView`
4. `paneView.renderer()` → 返回 `IPaneRenderer`
5. 框架在每帧重绘时调用 renderer.draw(ctx) 合并渲染

**内置插件**：
| 插件 | 功能 | 渲染方式 |
|------|------|---------|
| SeriesMarkers | K 线标记（买入/卖出箭头、形状标注） | 覆盖在主图 |
| TextWatermark | 文字水印 | 全图覆盖 |
| ImageWatermark | 图片水印（attribution logo） | 右下角 |
| UpDownMarkersPlugin | 涨跌标记 | 覆盖在主图 |

白泽的诊断结果（军规 RED/YELLOW 标记、博弈论拥挤度、大师多空信号）可以天然映射为 SeriesMarkers 和自定义 Primitive。

### 2.4 数据聚合与并发控制（DataConflater）

```typescript
class DataConflater {
  private readonly _interval: number        // 合并间隔
  private _timeoutId: ReturnType<typeof setTimeout> | null
  private readonly _state: Record<string, unknown>  // 待合并状态

  public walk(
    fn: (state: Record<string, unknown>) => void
  ): void { ... }

  public destroy(): void
}
```

设计目的：高频数据更新（tick 级别）不需要每笔都触发重绘。DataConflater 将多个更新合并到下一帧一次处理，避免 Canvas 过渡重绘。白泽的 T+0 分时/逐笔数据推送可借鉴同一模式。

### 2.5 品种化 Series 多态体系

```typescript
// 统一接口
interface ISeriesApi<TSeriesType> {
  setData(data: SeriesDataEntry<TSeriesType>[]): void
  update(bar: SeriesDataEntry<TSeriesType>): void
  priceScale(): IPriceScaleApi
  seriesType(): TSeriesType
  markers(): SeriesMarker<Time>[]
  setMarkers(data: SeriesMarker<Time>[]): void
  attachPrimitive(primitive: ISeriesPrimitive<TSeriesType>): void
}

// 品种类型（6 种内置 + Custom）
LineSeries          // 折线图（MA/NORTHBOUND/INDEX）
CandlestickSeries   // K 线图
BarSeries           // 美国线
AreaSeries          // 面积图（VWAP/量价分布）
HistogramSeries     // 柱状图（成交量/BUY/SELL）
BaselineSeries      // 基准线图
CustomSeries        // 自定义绘制（完全由插件控制）

// 每个品种的数据结构
type LineData = { time: Time; value: number }
type CandlestickData = { time: Time; open: number; high: number; low: number; close: number }
type HistogramData = { time: Time; value: number; color?: string }
```

这种统一接口 + 多态品种的模式，让白泽的多维分析结果可以按类型选择图表呈现。

---

## 三、关键技术细节

### 3.1 Canvas 渲染优化

| 技术 | 实现 | 白泽借鉴价值 |
|------|------|-------------|
| **延迟重绘** | `invalidateMask` 标记脏区域，requestAnimationFrame 批量绘制 | T+0 分时图更新 |
| **CompositeRenderer** | 多个 Renderer 合并到一个 Canvas 操作 | 指标叠加（MA+MACD+KDJ） |
| **TextWidthCache** | Canvas.measureText() 结果缓存 | 提高大量文本（Tick 标记）的场景 |
| **GradientStyleCache** | CanvasGradient 对象缓存 | 涨跌渐变填充 |
| **BitmapCoordinates** | Renderer 在像素坐标系操作，避免高 DPI 模糊 | 高清屏适配（devicePixelRatio） |
| **MediaCoordinates** | Renderer 在逻辑坐标系操作，自动映射到像素 | 跨屏一致性 |
| **animation** | kineticAnimation 物理动画（惯性滑动） | 移动端触摸交互 |

### 3.2 时间尺度（TimeScale）设计

```typescript
interface HorzScaleBehavior {
  // 时间轴刻度生成策略（可替换）
  calculateTickMarks(): TickMark[]
  formatTickMark(): string
  
  // 权重计算（决定哪些时间点的数据被采样显示）
  weight(): number
  
  // 时间轴可见范围（自动对齐到完整 K 线）
  visibleRange(): VisibleTimeRange
}
```

两种 Behavior：
- **TimeHorzScaleBehavior**：基于时间戳，适合日线/周线/月线
- **IndexHorzScaleBehavior**：基于索引，适合自定义 x 轴

visibleRange 自动对齐到最小时间粒度（日线→日期边界，分钟→分钟边界），防止展示不完整的 K 线。

### 3.3 十字光标（Crosshair）系统

```
Crosshair ──┬── CrosshairPaneView（主图十字线）
            ├── CrosshairPriceAxisView（价格轴标记）
            ├── CrosshairTimeAxisView（时间轴标记）
            └── MarksPaneView（特殊位置标记线）

CrosshairMode:
  - CrosshairMode.Normal（默认，自由移动）
  - CrosshairMode.Magnet（吸附到最近 K 线）
  - CrosshairMode.Hidden（隐藏）

模式切换 ↕️ Coordinate 映射：
  Crosshair → 点击坐标 → priceScale.coordinateToPrice(y)
                        → timeScale.coordinateToTime(x)
```

### 3.4 价格标记（PriceLine）系统

```typescript
// 自动价格线
autoScale: boolean    // 是否自动缩放
priceLines: []        // 自定义水平线（止损/止盈/支撑/阻力）

// Series 内置价格线
series.createPriceLine({
  price: 15.0,
  color: 'rgba(0, 0, 0, 0.5)',
  lineStyle: LineStyle.Dotted,
  axisLabelVisible: true,
  title: 'Pivot'
})

// 最后价格线（Latest Price Line）
lastPriceLine: SeriesOptions 控制显示
```

### 3.5 颜色编码方案

涨跌颜色通过 `SeriesBarColorer` 统一管理：

```typescript
interface SeriesBarColorer {
  barStyle(barIndex): BarColorerStyle
  // upColor / downColor / flatColor（CandlestickSeries）
  // lineColor / topColor / bottomColor（AreaSeries）
  // baseColor（BaselineSeries）
}
```

内部逻辑：
- `upColor`（涨）默认为 #089981（绿色，A 股标准）
- `downColor`（跌）默认为 #f23645（红色，A 股标准）
- 根据 `wickUpColor` / `wickDownColor` 等子选项细分

---

## 四、可迁移机制清单

| # | 机制 | 来源 | 应用到本项目 |
|---|------|------|------------|
| 1 | **Model/View/Renderer 三层分离** | 核心架构 | 数据分析结果的可视化映射：白泽多维诊断结果 → 雷达图/仪表盘 |
| 2 | **品种化 Series 多态体系** | `src/model/iseries.ts` | 白泽输出建模：Candlestick（行情）/ Line（均线/北向）/ Histogram（成交量） |
| 3 | **Scale 坐标映射（Time + Price）** | `time-scale.ts` + `price-scale.ts` | 诊断分数→可视化坐标的统一映射模型 |
| 4 | **ISeriesPrimitive 插件接口** | `src/plugins/types.ts` | 军规标记、博弈论拥挤度、大师信号→图表标注 |
| 5 | **DataConflater 合并更新** | `src/model/data-conflater.ts` | T+0 逐笔数据推送去重/合并重绘 |
| 6 | **Crosshair Mode 切换** | `src/model/crosshair.ts` | 交互式分析：Magnet 模式吸附到关键数据点 |
| 7 | **Canvas TextWidthCache** | `src/model/text-width-cache.ts` | 大量文本渲染的场景（板块排名表、Tick 等） |
| 8 | **涨跌颜色方案（upColor/downColor）** | `src/model/series-bar-colorer.ts` | A 股红绿配色标准化 |
| 9 | **PriceLine 系统** | `src/model/custom-price-line.ts` | 止损/止盈/支撑/阻力价位可视化标记 |
| 10 | **HorzScaleBehavior 可替换策略** | `src/model/ihorz-scale-behavior.ts` | 支持 time-based / index-based 两种 x 轴模式 |
| 11 | **kineticAnimation 惯性动画** | `src/model/kinetic-animation.ts` | 移动端触摸滑动交互 |
| 12 | **PriceFormatter 多格式** | `src/formatters/` | 金额/百分比/指数点 多格式输出 |
| 13 | **CompositeRenderer 合并渲染** | `src/renderers/composite-renderer.ts` | 多指标叠加（MA + MACD + KDJ + Volume） |
| 14 | **Agent Skill 文件** | `.github/skills/lightweight-charts/SKILL.md` | 为白泽 CLI/API 编写 AI Coding Assistant 技能文件 |

---

## 五、与现有参考的分工

| 主题 | 现有参考 | lightweight-charts 角色 |
|------|---------|----------------------|
| **前端可视化** | go-stock（自研 Canvas K 线组件） | industry-standard API 设计 + 插件体系的参考标杆 |
| **桌面应用** | go-stock（Wails + NaiveUI） | 作为 Web 前端备选方案（React/Vue 集成 Lightweight Charts） |
| **交互分析** | — | Crosshair / PriceLine / Marker 交互机制 |
| **性能优化** | — | Canvas 渲染优化（TextWidthCache / DataConflater / CompositeRenderer） |
| **投资决策输出** | worth-buy-stocks（评分引擎） | 评分结果的可视化呈现层 |

go-stock 自研 K 线组件的价值在于**原生集成和性能调控**，lightweight-charts 的价值在于**工业级 API 设计和插件扩展体系**——两者互补，前者提供落地参考，后者提供设计标杆。

---

## 六、建议落地优先级

| 优先级 | 项目 | 预期收益 |
|:------:|------|---------|
| **P0** | `diagnose` / `tactics` 输出增加 HTML 可视化（嵌入 Lightweight Charts） | CLI 输出 → 可交互图表，大幅提升分析可读性 |
| **P1** | 借鉴 Series 多态体系重构白泽输出建模 | 统一行情/因子/诊断的数据→图表映射 |
| **P1** | 基于 ISeriesPrimitive 实现军规标记/大师信号标注 | 分析结果的直觉化呈现 |
| **P2** | Crosshair + PriceLine 交互系统 | 交互式支撑/阻力/止损标记 |
| **P2** | DataConflater 模式应用于 T+0 逐笔处理 | 高频数据更新性能优化 |
| **P3** | CompositeRenderer 多指标叠加渲染 | 多因子同时展示（MA+MACD+KDJ+Volume+北向） |
| **P3** | 为白泽 CLI 编写 AI Skill 文件 | 降低其他 AI Code Assistant 使用白泽的门槛 |

> ⚠️ **注意**：lightweight-charts 是纯前端展示组件，不包含交易逻辑、数据获取、分析管道。白泽的核心价值在于后端的量化分析管道，前端可视化是分析结果的呈现层。建议先做好分析管道的数据模型（DTO）设计，再映射到 lightweight-charts 的 Series 模型上。go-stock 的自研 K 线组件可作为原生集成的先行方案，lightweight-charts 作为 Web 展示层的标准方案。
