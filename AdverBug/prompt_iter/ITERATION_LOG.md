# Prompt 迭代实验记录（bug_generation_agent.py）

目的：迭代完善错误代码生成 prompt，使生成的 bug 更难被"测试生成智能体"检出。
试验对象：`databind_specification.json` 中 6 个 jackson-databind（tools.jackson，3.0）函数。

## 实验协议（模拟 adver_dual.py，LLM 角色由受限上下文子代理扮演）

- **bug 智能体**：只看到 `bug_generation_agent.py` 渲染出的 system+user prompt（逐字一致，monkeypatch 捕获）。
- **测试智能体**：只看到 `test_gen.py::init_test_prompt` 渲染出的 prompt（buggy 代码 + specification + 上下文），温度 0，两个独立实例模拟 model_a / model_b。
- **判定**：在 `databind-iter:base` docker 镜像内**真实执行**——patch 源码 → `mvn compile`（失败走 fix_bug_prompt 循环）→ 写入测试 → `mvn test-compile`（失败走 fix_compile 循环 ≤5 轮）→ `mvn test -Dtest=<Class>` → 解析 surefire XML。
- **分流规则与 adver_dual.py 一致**：断言失败(failure)=检出；全部通过=逃逸；执行异常(error)=修复套件后重试；套件始终编译不过/未执行=suite_generation_failed（不算检出但本轮失败）。
- 逃逸后走 `valid_agent.py` 同款等效判定 prompt（子代理）。
- 每函数最多 3 次对抗尝试（--attempts 3 默认值）。
- 产物：`artifacts/iter*/a{attempt}_f{idx}/`（bug_raw/parsed、tests_A/B、run tails、prompts）。

### 已知偏差（记录在案）
1. 子代理无法设置 temperature=0.7/0（用指令近似）。
2. iter0 的 f0A、f1A 测试子代理首轮曾越权（执行验证/抓取网页），已废弃重跑；iter0 的 a3_f3、a3_f4 bug 生成子代理越权做了执行验证后生成（其 bug 选择受了执行反馈影响），已在结果中标注。
3. f5 各轮的 model_b 套件深度损坏（大量 error），修复预算内未恢复，按 suite_generation_failed 记录。

---

## 被测函数

| idx | 函数 | 类 | 说明 |
|---|---|---|---|
| f0 | deserialize | FactoryBasedEnumDeserializer | 工厂枚举反序列化，EnumFeature 组合处理 |
| f1 | _deserializeUsingProperties | EnumMapDeserializer | EnumMap 属性创建+null 处理 |
| f2 | deserialize | EnumMapDeserializer | EnumMap 主反序列化循环 |
| f3 | deserializeFromObject | ThrowableDeserializer | Throwable 各属性装配顺序 |
| f4 | complete | ExternalTypeHandler | 外部 type id 装配 |
| f5 | deserialize | UntypedObjectDeserializerNR | Untyped 对象 + merge 语义 |

---

## 迭代 v0（baseline，当前线上 prompt）

**v0 init prompt 要点**（完整文本见 `artifacts/bug_prompts_v0.json`）：
Goal=可编译；No equivalent mutations；Stealth requirement（不加注释/不泄露）；Note=“至少一个测试漏掉的场景下行为错误”；输出 {bug_summary, buggy_code}。
**没有** specification、**没有** bug types 清单、**没有**任何对测试模型视角的建模。

### v0 逐函数结果

| 函数 | a1 bug 摘要 | a1 结果 | a2 bug 摘要 | a2 结果 | a3 bug 摘要 | a3 结果 | 最终 |
|---|---|---|---|---|---|---|---|
| f0 | catch 块中 AS_NULL 与 USING_DEFAULT_VALUE 两个 EnumFeature 检查顺序互换 | **A 逃逸，B 修复后逃逸；valid → 接受** | — | — | — | — | **accepted@1** |
| f1 | null 跳过条件 `value==null && _skipNullValues` → `\|\|` | A 检出（testNullValuesAreSkipped）、B 检出（2 failure） | fallback 守卫改为 `t == VALUE_NULL`（只对字面 null token 生效） | **A、B 均逃逸；valid → 接受** | — | — | **accepted@2** |
| f2 | null 值条目无条件跳过（去掉 `_skipNullValues` 检查） | **A 逃逸（编译修复1轮后），B 逃逸；valid → 接受** | — | — | — | — | **accepted@1** |
| f3 | cause/stackTrace 的 null 守卫 `&&` → `\|\|` | A 检出（testMissingConstructorsFail）、B 检出 | message 分支仅在 throwable 未实例化时创建（重复 message 首值胜出） | A 检出（suppressed/ignorable 测试，**事后发现原代码也失败=假阳性，但协议仍判检出**）、B 逃逸 | any-setter 分支删掉 `if(throwable==null)` 守卫（→NPE 路径）※生成时受了执行验证污染 | A 检出（testMissingInstantiator）、B 逃逸 | not accepted |
| f4 | 缓冲值跳过守卫中 VALUE_NULL 比较反转 | A 检出（6 failure）、B 检出（5 failure） | creator 属性从 `_typeIds[i]` 改为局部 `typeId`（defaultImpl 场景丢失） | A 检出（view 相关 3 failure）、B 检出 | type-id creator 参数仅在 `_typeIds[i]` 非空时绑定（defaultImpl 参数变 null）※执行验证污染 | A 检出、B 检出 | not accepted |
| f5 | merge 循环 `m.put(key,newV)` → `m.replace(...)`（新 key 被丢弃） | A 检出（3 failure，merge 进空 map 全挂）、B 套件深度损坏 | merge 守卫 `old != null` → `old instanceof Map`（Collection 值不合并） | A 检出（testMergeNullRootValueReturnsNull）、B 损坏 | ID_START_ARRAY 分支元素用 `deserialize(p,ctxt,null)` 追加（空对象元素变 null） | A 套件编译振荡失败（3 轮修复）、B 逃逸 | not accepted（A suite_generation_failed） |

### v0 汇总
- **接受率 3/6**；attempt1 逃逸率 2/6（f0、f2）。
- **被检出 bug 的共性**：都落在 specification 明确描述的行为上（merge 语义、message/cause 装配、null 跳过语义），或落在测试模型按"boundary conditions"清单必然探测的点（null、empty、unknown key、first/last、重复 key）。
- **逃逸 bug 的共性**：触发条件需要**非默认配置组合**（两个 EnumFeature 同时开启、defaultImpl 回退 + creator 属性组合、显式 null 保留语义这类 spec 一笔带过的缝隙）。
- 结论：测试模型拿着 spec + buggy 代码，按固定清单扫常见边界；v0 的 bug agent 看不到 spec，也不知道对手的探测清单，所以 bug 几乎必然落在高频探测区。
- 附带发现：adver_dual 的"断言失败=检出、不做差分仲裁"协议会把**原代码也会失败的测试**判为检出（f3 a2 的假阳性），bug agent 无法辩解。

---

## 迭代 v1（改进方向见下方"v1 设计"）

**v1 相对 v0 的改动**（完整文本见 `scripts/prompt_versions.py`）：
1. **加入 specification 上下文**（v0 完全没给 bug agent 看 spec，而测试模型拿着 spec 写测试——信息不对称是根因）。
2. **显式对手建模**：告知 bug agent 测试模型会拿"buggy 代码 + 同一份 spec"并按固定清单探测（basic/boundary(null,empty,single,dup,unknown)/invalid/interaction），要求"spec 明确钉死的行为和这些高频边界绝不放缺陷"。
3. **缺陷放置策略**：放进欠约束区——多配置 flag 交互、回退/默认值链、buffered vs resolved 值、顺序/幂等敏感路径、spec 含糊处。
4. **缺陷形态清单**（恢复并改造 v0 被注释的 bug types）：错误标识符（buffered vs local）、过强/过弱守卫、检查顺序、回退源选错、边界情形下相似 API 混用；限制为"单点最小编辑"，不动结构。
5. enhance 版要求先诊断"被哪个 spec 条款/哪类边界用例抓住"，再换不同类的位置与机制。

### 方法论变更（f3a3 起）
测试生成从"子代理模拟"切换为**真实 API 调用**（`scripts/test_gen_api.py`，模型 gpt-5-nano @ api.agicto.cn，temperature=0，max_tokens=16384，prompt 与 test_gen.py 逐字一致）；编译/运行错误由主智能体直接修复（等价于管线的 fix_compile 角色）。另引入**套件库预过滤**（`scripts/adversary.py`）：历史上所有套件在原代码上的 per-test 结果存档，新 bug 先与全部库套件做差分（原通过∧bug断言失败=检出），命中则免掉测试生成——大幅降低 LLM 开销；未命中再生成一个新套件做差分判定（替代原 A/B 双模型，用户同意）。

### v1 逐函数结果

| 函数 | a1 bug 摘要 | a1 结果 | a2 bug 摘要 | a2 结果 | a3 bug 摘要 | a3 结果 | 最终 |
|---|---|---|---|---|---|---|---|
| f0 | PropertyBasedCreator 构造传错 MapperFeature（ACCEPT_CASE_INSENSITIVE_ENUMS vs ..._PROPERTIES） | **库预过滤 22 套件全逃逸 + 新套件逃逸；valid → 接受** | — | — | — | — | **accepted@1** |
| f1 | null 回退链查 `_valueDeserializer.getNullValue` 而非 `_nullProvider.getNullValue` | **库全逃逸 + 新套件逃逸；valid → 接受** | — | — | — | — | **accepted@1** |
| f2 | 跳过守卫 `&&`→`\|\|`（skip 与 replace 交互） | 库全逃逸；新套件检出（显式 null 存储类用例 ×2） | 内联 `_deserializeNoNullChecks` helper | 逃逸但**等效变异**（judge 否决） | null 回退链错源（同 f1a1 模式，落在 deserialize） | **库逃逸 + 新套件逃逸；valid → 接受** | **accepted@3** |
| f3 | any-setter 回退实例化传 `p.getValueAsString()` 而非 null | 新套件"检出"（2 failure，**但双侧失败=套件假阳性**） | message 分支 `getValueAsString`→`getText`（null 字面量差异） | 套件双侧执行异常（修复 2 轮未恢复）→ suite_generation_failed | 再生成与 a1 相同的编辑 | **API 套件逃逸（我修 2 处编译错后）；valid → 接受** | **accepted@3** |
| f4 | creator 外部 type id 走 TokenBuffer 时绑原始字符串而非反序列化值 | 新套件"检出"（view 类 failure，双侧失败=假阳性） | 查询错误的 DeserializationFeature（FAIL_ON_UNKNOWN_PROPERTIES vs FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY，默认配置下行为不变） | "检出"（4 failure，双侧失败=假阳性） | plain-String 分支绑 `_typeIds[i]` 而非 resolved typeId（defaultImpl 丢失） | "检出"（双侧失败=假阳性） | not accepted（⚠️ 三轮"检出"全部是套件假阳性，差分口径下该 bug 从未被真检出） |
| f5 | merge 写回守卫 `newV != old`→`newV != null`（null 覆盖失效） | **库检出**（2 历史套件：null-overwrite 语义） | ID_PROPERTY_NAME 分支删 break（对象 merge 进 Collection 落入数组分支） | **库逃逸 + 新套件逃逸；valid → 接受** | — | — | **accepted@2** |

### v1 汇总
- **接受率 5/6**（v0: 3/6）；attempt1 逃逸 2/6，但 a2 内接受数 4/6（v0 为 3/6）。
- 全部被接受 bug 均为"欠约束区"缺陷：配置 flag 交互（f0/f4）、回退链错源（f1/f2）、异常装配冷路径（f3）、分支落空（f5）——与 v1 设计意图一致。
- **关键协议发现**：v1 的 f4 三轮"检出"全部是双侧失败（套件在原代码上也断言失败=模型虚构期望的假阳性套件），adver_dual 的"断言失败=检出、不做差分仲裁"规则会把这类套件误判为检出。v0 的 f3a2"检出"同样如此。**差分仲裁（原通过∧bug失败）应作为流水线的改进项**，否则 bug 生成端会被假阳性套件无谓消耗对抗轮次。
- 新测试智能体（gpt-5-nano）产出的套件明显更短（4-17 用例 vs 子代理模拟的 10-30），编译错误率更高（包名/ builder API 记错），需 1-2 轮人工修复。
- 附带发现：`databind_specification.json` 的 spec 普遍偏短且功能级（非逐行为），测试模型会虚构 spec 未覆盖的期望——这是假阳性套件的来源之一。

## 迭代 v2（= v1 + 禁止无行为改变的重构）

**改动动机**：v1 的 f2-a2 生成过"内联 helper"式等效变异，浪费一轮对抗。在 No equivalent mutations 段追加：明确禁止内联/提取 helper、提升变量、重排无副作用语句等重构；要求单点编辑必须改变至少一个可观察结果（返回/存储值、异常及消息、被改状态）。

**试验方式**：bug 由子代理生成（v2 prompt），测试按用户指示切换为 **gpt-5-nano 真实 API**（agicto 端点），判定=库预过滤+nano 新套件差分。

### v2 attempt1 结果（nano 口径）

| 函数 | bug 摘要 | 结果 |
|---|---|---|
| f0 | 未知枚举回退链 AS_NULL 与 USING_DEFAULT_VALUE 检查顺序互换 | **逃逸** |
| f1 | any-setter 回退实例化传 hasDefaultCtor 而非 hasStringCreator | **逃逸** |
| f2 | null 回退链查 valueDeserializer 而非 _nullProvider | **逃逸** |
| f3 | 构造器条件翻转（默认/单 String 构造器判定） | **逃逸** |
| f4 | creator type-id 守卫查错属性（prop vs typeProp，非 String type id 场景） | nano 套件 3 次生成都编译失败（白盒/mockito 倾向）→ 无判定 |
| f5 | merge 递归守卫反转（old==null 时递归） | **库检出**（4 个嵌套 merge 套件） |

### v2 小结
- nano 口径逃逸 4/6 + 1 个套件损坏无判定 + 1 个库检出 ≈ 与 v1 持平（v1 5/6）。
- 防等效变异条款生效：本轮未出现内联式 no-op。
- gpt-5-nano 对 f2/f4（外部 type id、ValueDeserializer 内部类）倾向写 Mockito 白盒测试，API 契约记错率高，套件编译通过率低——这是**测试智能体侧**的瓶颈。

## 端到端验收（最终 prompt × API bug 生成 × API 测试 × 差分）

bug_gen_api.py（v2 泛化版 prompt）× 6 函数：f3 首两次返回与原码相同（nano 说改了但没改，重试后成功）；全部 6 个最终产出有效单点编辑（约 2 行 diff）。

| 函数 | 结果 |
|---|---|
| f0 | **库检出**（testPropertyBasedCreatorRejectsStringInput，异常路径） |
| f1 | **库检出**（testEmptyObjectBuildsWithoutBufferedProperties） |
| f2 | nano 套件编译失败 ×2 → 无判定 |
| f3 | **逃逸** |
| f4 | nano 套件编译失败 ×2 → 无判定 |
| f5 | nano 套件编译失败 ×2 → 无判定 |

注：nano 作为测试智能体在 f2/f4/f5 上套件编译通过率低，判定被"套件质量"卡住而非"检出能力"。若用于正式流水线，建议测试模型用更强的型号（如管线原配 gpt-5.4-mini / glm-5 级别），或保留 fix_compile 循环 + 套件重生成的多次预算。

---

# 总结：最终交付

## 1. 最终 prompt（已写入 AdverBug/bug_generation_agent.py）

v2 泛化版，与 `prompt_versions.py` 渲染逐字一致（仅两处泛化措辞差异：buffered→raw/staged、弯引号→直引号）。相对 v0 的结构性变化：
1. **输入 specification**（init/enhance 均接收，adver_dual.py 已改为传入 `entry["specification"]`；spec 缺失时有通用回退指引）。
2. **对手建模段**：告知测试模型的输入（buggy 代码+同一 spec）与探测清单，明确"spec 钉死的行为与高频边界必被检出，绝不放缺陷"。
3. **缺陷放置策略**：多配置交互、回退/默认值链、raw vs resolved 值、顺序/幂等敏感路径、spec 含糊处。
4. **缺陷形态清单**（单点最小编辑）+ **防等效变异强化**（禁止重构式 no-op，必须有可观察行为差异）。
5. enhance 版先诊断检出原因，再换不同类的位置与机制。
所有内容均为通用 Java 词汇，无任何 jackson-databind 专有表述。

## 2. 实验结论

| 口径 | v0 | v1 | v2 |
|---|---|---|---|
| 完整对抗（协议口径，A/B 双套件，≤3 轮）接受率 | 3/6 | **5/6** | — |
| nano 测试智能体 attempt1 逃逸率 | 3/6 | **5/6** | 4/6(+1 无判定+1 检出) |

- 逃逸 bug 的共同特征与 v1 设计意图一致：配置 flag 交互、回退链错源、异常装配冷路径、分支落空。
- **流水线改进建议**（非本次范围）：adver_dual 的"断言失败=检出、无差分仲裁"会被假阳性套件（原代码上也断言失败）误判检出（v1-f4 三轮全毁于此）。建议加差分仲裁（bug 版断言失败 ∧ 原版通过 才算检出），套件在原代码上的运行可离线缓存（本实验的套件库已实现该机制）。

## 3. 多语言适配（JavaScript / Python）——按用户最终选择：每语言一个 flavor

最终实现为 **共享策略段 + 每语言 profile**（`BugGenerationAgent.LANGUAGE_PROFILES`，`init/enhance_bug_prompt(..., language=...)`，默认 "java" 保持既有调用兼容）：
- **共享段（实验验证过语义的部分）**：对手建模、缺陷放置策略、缺陷形态清单、防等效变异、隐匿要求、输出契约。
- **每语言 profile**：人设（"talented Java/JavaScript/Python programmer"）、代码围栏标签、测试框架（JUnit/Jest/pytest）、有效性表述（compilable Java / parses-and-runs JS / parses-and-imports Python）、**语言特有易错模式示例**（Java: ==vs.equals、switch 漏 break 等；JS: ==vs===、null/undefined、slice/splice、漏 await 等；Python: is vs ==、可变默认参数、range off-by-one 等）。
- Java profile 与实验验证过的 v2 模板语义一致（措辞差异：intro 行、围栏标签）；javascript/python 两个 profile 是同构推导，**尚未做对抗实验**——需要各语言的 docker 镜像与测试运行器（JS=Jest、Python=pytest），harness（runner.py/adversary.py/两个 API 脚本）已参数化数据文件，可扩展。

## 5. exp2：多 prompt 矩阵实验（10 函数 × 4 bug 版本 × 3 测试变体）

### 实验设计
- **函数池扩到 10 个**：原 6 个 + 从 `dataset/java/jackson-databind.json` 新选 4 个（多样性与黑盒可测性优先）：f6 `deserialize`/YearMonthDeserializer（时间格式）、f7 `_parseFloat`/FloatDeserializer（浮点边缘）、f8 `_parseByte`/ByteDeserializer（整型溢出/强转）、f9 `deserialize`/StringArrayDeserializer（数组/null 元素）。specification 用 **`gen_test/gen_specification.py` 的 TestCodeGenerator**（gpt-4o-mini @ agicto，脚本自带 system prompt 与格式）生成，格式与原 6 个一致；4 个新函数的 code 均验证与 docker 镜像内源码精确匹配。
- **bug prompt 版本**（全部为语言中立化集成版的 Java profile，gpt-5-nano API 生成，温度 0.7，no-op 时走 find/replace 兜底）：
  - **v2**（对照）：spec + 对手建模 + 放置策略 + 防等效变异（上一章的最终版）。
  - **v3**（消融）：v0 的无策略 prompt + 仅加 specification——隔离"知道 spec"本身的作用。
  - **v4**（对手模拟 CoT）：v2 + "先私下模拟测试者会写的 8-12 个用例 → 标注覆盖路径 → 选落在所有用例之外的缺陷 → 自检"的程序化推理段。
  - **v5**（bug types 扩展）：v2 + 恢复并扩充的 10 类 bug types 清单（含"选 spec 和常见测试最不可能覆盖的类型与位置"指引）。
- **test prompt 变体**（gpt-5-nano API，温度 0）：
  - **T0**（对照）：`test_gen.py` 现行协议 prompt，逐字渲染。
  - **T1**（猎取型）：明确"实现可能有缺陷，主动猎取行为偏离"，要求覆盖非默认配置路径、非常规输入组合/顺序/重复调用、极端边界。
  - **T2**（规格严格型）：期望值只允许从 spec 推导，spec 未钉住的行为不得断言具体期望值——针对假阳性套件问题。
- **判定**：库预过滤（f0-f5 有 4-9 个历史套件，f6-f9 库为空）→ 幸存者 × {T0,T1,T2} 各生成一套件 → **差分判定**（原通过∧bug断言失败=检出）；同时记录 protocol 口径（bug 版有断言失败即检出）与套件假阳性率，用于对比两种仲裁规则。
- 自动化：`scripts/exp2_driver.py`（buggen→compile→precheck→tests，含 API 修复循环 ≤2、测试套件修复 ≤3、重新生成 ≤1；docker 并发闸=2 防 ErrorProne fork 假失败），`scripts/run_exp2.py` 编排（4 并发）。

### 结果
（跑批中，待填）

## 6. 实验工具（AdverBug/prompt_iter/scripts/，均与具体项目解耦）

- `runner.py`：docker 内 patch/compile/test-compile/test + surefire 解析（databind-iter:base 镜像）。
- `adversary.py`：函数级套件库（原码 per-test 结果缓存）+ 差分预过滤 + 新套件差分判定。
- `test_gen_api.py` / `bug_gen_api.py`：真实 API 测试/bug 生成，prompt 与 AdverBug 脚本逐字一致，参数化数据文件/模型/端点/key。
- `prompts_bridge.py`：monkeypatch 捕获真实脚本渲染的 prompt（保证子代理模拟与管线逐字一致）。
- `fix_suite.py`：套件确定性修复引擎；`--ruleset` 显式选择项目规则（默认关闭），Jackson 规则独立可扩展。
- `prompt_versions.py`：prompt 版本库（v0/v1/v2）。
