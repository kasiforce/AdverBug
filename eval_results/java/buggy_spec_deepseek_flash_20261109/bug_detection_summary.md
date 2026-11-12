# buggy-code + specification 测试检错结果

执行日期：2026-11-11

检出定义：同一个生成测试在原始源码上通过、在对应错误代码上失败。

## 汇总

| 项目 | 目标数 | 源代码通过 | 错误代码失败 | 严格检出数 | 按全部目标 | 按源代码通过目标 |
|---|---:|---:|---:|---:|---:|---:|
| TwelveMonkeys | 9 | 7 | 2 | 1 | 11.11% | 14.29% |
| Thymeleaf | 9 | 5 | 1 | 1 | 11.11% | 20.00% |
| Parquet | 3 | 0 | 0 | 0 | 0.00% | — |
| OFDRW | 2 | 0 | 0 | 0 | 0.00% | — |
| **合计** | **23** | **12** | **3** | **2** | **8.70%** | **16.67%** |

## 说明

- 23 个错误代码和生成测试全部完成编译与执行。
- 只有 12 个测试在原始源码上通过，因此只有这 12 个目标适合用于严格检错率计算。
- 严格检出 2 个：TwelveMonkeys `PredictorTransform.applyInverse`，Thymeleaf `DialectSetConfiguration.build`。
- Parquet 和 OFDRW 的 buggy-spec 测试均未在原始源码上通过，因此不能将其错误代码结果判定为有效检错。

## 结果目录

- `twelvemonkeys/original/` 与 `twelvemonkeys/buggy/`
- `thymeleaf/original/` 与 `thymeleaf/buggy/`
- `parquet/original/` 与 `parquet/buggy/`
- `ofdrw/original/` 与 `ofdrw/buggy/`

