# 四个 Java 项目的生成 Bug 分类与测试检测结果

生成日期：2026-11-11（修订：改用 Parquet specification 数据集）

## 1. 分析范围

本报告分析以下四个项目中已成功匹配 `buggy_code` 并实际运行生成测试的 23 个 bug：

| 项目 | 执行 Bug 数 | Killed | Survived | Mutation Score |
|---|---:|---:|---:|---:|
| TwelveMonkeys | 9 | 3 | 6 | 33.33% |
| Thymeleaf | 9 | 6 | 3 | 66.67% |
| Parquet | 3 | 1 | 2 | 33.33% |
| OFDRW | 2 | 1 | 1 | 50% |
| **合计** | **23** | **11** | **12** | **47.83%** |

这里的 `killed` 表示生成测试在错误代码上出现断言失败或错误，成功检测出 mutation；`survived` 表示错误代码成功编译且生成测试全部通过。

## 2. 总体错误分类

分类依据是错误代码相对源码引入的主要根因。一个 bug 可能有多个表现，本报告为每个 bug 选择一个主要类别。

| 主要错误类型 | 数量 | Killed | Survived | 检出率 | 具体示例 |
|---|---:|---:|---:|---:|---|
| 错误变量、字段或数据源 | 8 | 4 | 4 | 50% | TwelveMonkeys BMP：裁剪源图像时将 `getSourceBands()` 错换成 `getDestinationBands()`，导致源通道选择错误。 |
| 参数顺序、参数角色或坐标计算错误 | 3 | 1 | 2 | 33.33% | TwelveMonkeys WebP：将 `clampAddSubtractFull(left, top, topLeft)` 中的 `top` 与 `topLeft` 对调，重建出错误像素。 |
| 执行顺序或覆盖优先级错误 | 3 | 3 | 0 | 100% | Thymeleaf：先合并显式 model、后合并 path variables，使路径变量错误覆盖调用者显式提供的同名值。 |
| 条件强化或守卫条件错误 | 3 | 1 | 2 | 33.33% | Parquet：只有同时存在 Bloom-filter offset 时才复制 length，遗漏可独立存在的 length 元数据。 |
| 语义反转或逻辑生成错误 | 1 | 1 | 0 | 100% | Parquet：Eq/NotEq 生成代码使用了错误的字段结果处理逻辑。 |
| 算术公式错误 | 1 | 0 | 1 | 0% | TwelveMonkeys JPEG：预测初始值指数从 `precision - approxLow - 1` 变成 `precision - approxLow - selection - 1`，错误地多减了 `selection`。 |
| 状态机转换错误 | 1 | 0 | 1 | 0% | Thymeleaf：嵌套表达式关闭后过早设置 `inNothing=true`，使外层字面量替换的结束符被错误解释。 |
| 配置传播或限制绕过 | 2 | 1 | 1 | 50% | Parquet：同时配置 complete-column encryption 与 plaintext footer 时遗漏 complete-column 标志。 |
| 输入规范化或符号丢失 | 1 | 0 | 1 | 0% | OFDRW：解析 `-0x...` 前删除负号，把负数颜色编码错误地当作正数颜色解析。 |
| **合计** | **23** | **11** | **12** | **47.83%** | — |

## 3. TwelveMonkeys

| 函数 | 引入的错误 | 主要分类 | 结果 |
|---|---|---|---|
| `IndexImage.main` | 同时指定 palette image 和 background color 时，调色板生成错误地使用输入图像而不是指定的 palette image | 错误字段/API 选择 | killed |
| `BMPImageReader.read` | 裁剪源图像时使用 `destinationBands`，而不是 `sourceBands` | 错误字段/API 选择 | survived |
| `JPEGLosslessDecoder.decode` | 预测初始值计算中错误地额外减去 `selection` | 算术公式错误 | survived |
| `PCXImageReader.read` | 使用目标波段选择代替源波段选择 | 错误字段/API 选择 | survived |
| `TIFFImageReader.getRawImageType` | 使用最后一个 extra sample 判断 alpha 预乘，而不是建立 alpha 语义的第一个条目 | 错误数组元素/数据源 | survived |
| `PredictorTransform.applyInverse` | 交换 top 与 top-left 两个预测参数 | 参数角色交换 | killed |
| `LoopFilter.loopFilterUVBlock` | 使用 `loop_filter_level` 计算 sharpness 上限，而不是 `sharpnessLevel` | 错误变量 | killed |
| `VP8Frame.decode` | 交换 segmentation-enabled 与 absolute-delta 两个布尔参数 | 参数角色交换 | survived |
| `PSDImageReader.main` | 同时使用 source region 和 subsampling 时，错误地从 region 绝对起点计算 subsampling offset | 参数/坐标计算错误 | survived |

主要特征：

- 主要集中在值来源选错和参数角色交换。
- BMP 与 PCX 是同一种 mutation 模式：`sourceBands` 被替换为 `destinationBands`。
- survived bug 多数依赖罕见输入组合，例如不同的源/目标波段映射、特殊 JPEG scan 参数、多个 TIFF extra samples 或特殊 VP8 segmentation 配置。

结果文件：`eval_results/java/loc_ge_100/twelvemonkeys_buggy/evaluated_results.json`

## 4. Thymeleaf

| 函数 | 引入的错误 | 主要分类 | 结果 |
|---|---|---|---|
| Spring 5 `renderFragment` | 提前合并显式 model，导致 path variables 覆盖 model | 覆盖优先级错误 | killed |
| Spring 5 `renderFragmentInternal` | data-driven 模式强制使用 `Integer.MAX_VALUE`，忽略最大 chunk 配置 | 配置传播/限制绕过 | killed |
| Spring 6 `renderFragment` | path variables 覆盖显式 model | 覆盖优先级错误 | killed |
| Spring 6 `renderFragmentInternal` | path variables 覆盖 controller render attributes | 覆盖优先级错误 | killed |
| `DialectSetConfiguration.build` | 默认 prefix 从尚未设置的 configuration 读取，而不是从 dialect 读取 | 错误对象/数据源 | killed |
| `handleStandaloneElement` | 对延迟处理增加额外条件，导致部分 before-model 不进入 throttle 队列 | 条件强化 | survived |
| `handleOpenElement` | 使用 `setBodyModelProcessable` 代替 `insertImmediatelyAfterModelProcessable` | 错误状态标志 | survived |
| `performLiteralSubstitution` | 嵌套表达式关闭时提前设置 `inNothing=true` | 状态机转换错误 | survived |
| `parseAttributeSequence` | value 的行列位置错误使用 attribute name 的位置 | 错误元数据变量 | killed |

主要特征：

- 模型合并顺序是最明显的一组错误，共 3 个，全部被生成测试杀死。
- Spring 5 与 Spring 6 的同步视图 bug 属于同一种跨版本重复 mutation。
- `DialectSetConfiguration.build` 的错误代码对长方法进行了大量无意义格式重写，但主要语义变化只是将 `processorDialect.getPrefix()` 改为 `dialectConfiguration.getPrefix()`。这属于修改范围过大、实际语义变化很小的生成噪声。

结果文件：`eval_results/java/loc_ge_100/leaf_buggy/evaluated_results.json`

## 5. Parquet

| 函数 | 引入的错误 | 主要分类 | 结果 |
|---|---|---|---|
| `IncrementallyUpdatedFilterPredicateGenerator.run` | Eq/NotEq 生成代码使用重复字段结果处理，而不是标量字段处理 | 语义/逻辑生成错误 | killed |
| `EncryptionPropertiesReader.getFileEncryptionProperties` | 同时启用 complete-column encryption 和 plaintext footer 时遗漏 complete-column 标志 | 配置传播或限制绕过 | survived |
| `ParquetMetadataConverter.fromParquetMetadata` | 只有存在 Bloom-filter offset 时才复制 Bloom-filter length | 条件强化或守卫条件错误 | survived |

主要特征：

- `run` 的生成代码使用了错误的字段结果处理逻辑，source-code-only 测试成功检测到该错误。
- `getFileEncryptionProperties` 只有在 complete-column encryption 与 plaintext footer 同时配置时才暴露。
- `fromParquetMetadata` 只有在 Bloom-filter length 存在但 offset 不存在时才暴露。
- 三个 bug 都有明确的可观察语义差异，但现有生成测试没有覆盖相应的配置、元数据或生成代码语义。

结果文件：`eval_results/java/loc_ge_100/parquet_buggy/evaluated_results.json`

## 6. OFDRW

| 函数 | 引入的错误 | 主要分类 | 结果 |
|---|---|---|---|
| `TrueTypeFont.parse` | 读取 `name` 表被错误要求同时存在 `cmap` 表 | 条件强化/错误组件依赖 | killed |
| `NamedColor.rgb` | 解析 `-0x...` 前删除负号 | 输入规范化/符号丢失 | survived |

`TrueTypeFont.parse` 将：

```java
if (tables.containsKey("name"))
```

改为：

```java
if (tables.containsKey("name") && tables.containsKey("cmap"))
```

这会将两个独立的可选字体表错误绑定，使应执行的名称解析被跳过，属于条件强化导致的功能遗漏。

`NamedColor.rgb` 改变了带符号十六进制数的含义。Java 的实际行为为：

```text
Color.decode("-0x1a2b3c") -> RGB(229, 212, 196)
Color.decode("0x1a2b3c")  -> RGB(26, 43, 60)
```

现有测试没有覆盖负十六进制输入，因此该 bug survived。原始 `validation_result` 声称原代码会异常并返回 `null`，这一解释不准确；但 mutation 仍然会产生可观察的错误颜色。

结果文件：`eval_results/java/loc_ge_100/ofdrw_specification_restricted_gpt_20261102_buggy/evaluated_results.json`

## 7. Survived mutation 的二次复核

对 12 个 survived mutation 进一步结合生成测试的具体断言和目标方法控制流进行复核。这里区分：

- **输入/状态组合缺失**：测试执行了目标方法，但没有构造能激活错误的参数组合。
- **测试 oracle 不足**：错误可能已经影响中间结果，但断言没有验证正确语义，或只做自洽比较。
- **等价/被覆盖 mutation**：错误值在到达可观察输出之前被无条件覆盖，当前实现下无法由测试杀死。

| 项目与函数 | 未检出的直接原因 | 建议的杀死用例 | 复核结论 |
|---|---|---|---|
| TwelveMonkeys `BMPImageReader.read` | 38 个测试覆盖了默认读取、区域、缩放和非法 `sourceBands`，但没有合法且取值不同的 source/destination band 映射。错误行虽被执行，两个 band 配置通常都是 `null`。 | 对 24-bit RGB 设置等长但不同的映射，例如 `sourceBands={0,1,2}`、`destinationBands={2,1,0}`，断言各目标通道。 | 真实 bug；输入组合缺失。 |
| TwelveMonkeys `PCXImageReader.read` | 唯一相关测试只设置 `destinationBands={0}` 并预期参数校验失败，错误的通道复制阶段没有形成可观察结果。 | 对多平面 PCX 同时设置合法、等长且不同的 source/destination band 映射，断言每个输出通道。 | 真实 bug；输入组合缺失。 |
| TwelveMonkeys `TIFFImageReader.getRawImageType` | alpha 测试的 `ExtraSamples` 都只有一个元素，所以 `extraSamples[0]` 与 `extraSamples[length-1]` 是同一个值。 | 构造 `ExtraSamples={ASSOCIATED_ALPHA, UNSPECIFIED}`，断言 `hasAlpha()==true` 且 `isAlphaPremultiplied()==true`。 | 真实 bug；边界数据结构缺失。 |
| TwelveMonkeys `VP8Frame.decode` | 普通资源没有覆盖“segmentation enabled 且 absolute-delta=false”的相对分段模式；另外多项图像断言只检查非零或拿同一错误实现的完整解码结果作参照。 | 使用相对分段量化的 VP8 fixture，并与已知正确像素或各 segment 的预期 Q index 比较。 | 真实 bug；激活输入和独立 oracle 均不足。 |
| Thymeleaf `handleStandaloneElement` | mutation 只在 throttling 开启、只有 `modelBefore`、没有 `modelAfter` 时改变是否入队。现有 before+after 测试关闭 throttling，throttling 集成测试走 replacement 路径。 | throttled 渲染中仅调用 `insertBefore`，以很小 chunk 分段恢复执行，验证输出顺序和处理暂停边界。 | 真实 bug；状态组合缺失。 |
| Thymeleaf `handleOpenElement` | 现有 `insertImmediatelyAfter` 测试传入 `processable=false`；此时正确字段和误用的 `setBodyModelProcessable` 默认值同为 false，错误被相同布尔值掩盖。 | 调用 `insertImmediatelyAfter(model, true)`，让插入模型包含需要处理器执行的事件，并断言处理器确实执行。 | 真实 bug；布尔取值缺失。 |
| Thymeleaf `performLiteralSubstitution` | 虽然达到 100% 行覆盖和 94.34% 分支覆盖，也测试了 `${a{b}}`，但内层 `}` 后紧接外层 `}`，错误设置的 `inNothing=true` 没有被使用。需要在内层闭合与外层闭合之间出现 `|` 或新的表达式选择符才会暴露。 | 增加“嵌套花括号闭合后、外层表达式结束前仍含 pipe/selector”的用例，并断言完整转换字符串。 | 真实 bug；状态转换序列缺失，说明高覆盖率不等于 mutation 能力强。 |
| Parquet `IncrementallyUpdatedFilterPredicateGenerator.run` | source-code-only 测试在错误代码上失败，已检测到该错误。 | 保留该测试作为回归用例，并明确断言 Eq/NotEq 的标量比较结果。 | 已检测。 |
| Parquet `EncryptionPropertiesReader.getFileEncryptionProperties` | 没有同时覆盖 complete-column encryption 与 plaintext footer 的配置组合。 | 同时开启两个配置，断言返回的 `FileEncryptionProperties` 仍保留 complete-column-encryption 标志。 | 真实 bug；配置组合缺失。 |
| Parquet `ParquetMetadataConverter.fromParquetMetadata` | 没有覆盖 Bloom-filter length 存在但 offset 缺失的元数据组合。 | 构造仅设置 Bloom-filter length 的 column metadata，断言转换后 length 仍被保留。 | 真实 bug；元数据边界组合缺失。 |
| OFDRW `NamedColor.rgb` | 测试覆盖正十六进制、`0x`、十进制和非法输入，但没有任何 `-0x...` 输入；方法整体覆盖率也只有 26.90%。 | 断言 `rgb("-0x1a2b3c")` 等于 `Color.decode("-0x1a2b3c")` 的 RGB，即 `{229,212,196}`。 | 真实 bug；输入分区缺失，容易补测。 |
| TwelveMonkeys `JPEGLosslessDecoder.decode` | mutation 改变 `firstValue` 后，该值虽复制到 `pred`，但 `decodeSingle`、`decodeRGB` 或 `decodeAny` 会在真正解码前重新计算并覆盖所有预测值；首像素路径仍使用正确公式。已有 `selection=1, approxLow=1` 测试也通过。 | 在当前控制流下不存在仅靠输入即可杀死的用例；应先删除/重构死赋值，或将该 mutation 标为 equivalent。 | **等价/被覆盖 mutation，不应计入有效分母。** |

因此，修订后的原始执行结果为 23 个中 killed 11 个；若按 mutation testing 的通常做法排除 JPEG 这一等价 mutation，则有效 mutation 为 22 个，mutation score 为 `11/22 = 50%`，剩余有效 survived 为 11 个。

## 8. 综合观察

1. 错误变量、字段或数据源选择是最常见的类型，占 `7/21 = 33.33%`。这类 bug 通常只修改一个标识符，语法正确且比较自然。
2. 合并顺序和覆盖优先级错误最容易被当前测试发现，3 个全部 killed。这类错误的触发输入容易构造，输出也直接可见。
3. 除 JPEG predictor mutation 外，其余 survived bug 都有明确可观察差异；主要缺口包括不同的 source/destination bands、多个 TIFF extra samples、相对分段 VP8、Parquet 加密 metadata、Thymeleaf throttling/processable 状态组合和带符号十六进制颜色。
4. 23 个 bug 实例不等于 23 种独立错误模式。BMP/PCX 的波段选择错误以及 Spring 5/Spring 6 的 model 合并顺序错误都是明显的重复模式。
5. 大部分 bug 是局部、可编译、可观察的语义错误，但 JPEG predictor mutation 的错误值会被后续逻辑无条件覆盖，应标记为等价 mutation；此外仍存在大范围无意义重写以及 bug 行为解释不准确的问题。

## 9. 数据来源

- `results/loc_ge_100/java/parquet_deepseek_testgen.json`（Parquet source-code-only 生成测试）
- `results/loc_ge_100/java/twelvemonkeys_deepseek_testgen.json`（TwelveMonkeys source-code-only 生成测试）
- `test_results/java/TwelveMonkeys/adver_100/final_results.json`
- `test_results/java/thymeleaf/adver_100/final_results.json`
- `test_results/java/parquet-java/parquet_specification_restricted_gpt_20261102/final_results.json`
- `test_results/java/ofdrw/ofdrw_specification_restricted_gpt_20261102/final_results.json`
- `eval_results/java/loc_ge_100/twelvemonkeys_buggy/`
- `eval_results/java/loc_ge_100/leaf_buggy/`
- `eval_results/java/loc_ge_100/parquet_buggy/`
- `eval_results/java/loc_ge_100/ofdrw_specification_restricted_gpt_20261102_buggy/`
