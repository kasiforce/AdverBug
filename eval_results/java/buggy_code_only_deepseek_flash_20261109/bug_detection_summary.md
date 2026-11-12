# Bug Detection Summary

评测目录：`eval_results/java/buggy_code_only_deepseek_flash_20261109`

## 判定口径

逐个目标配对 `original/evaluated_results.json` 与 `buggy/evaluated_results.json`。只有同时满足以下条件才算测试检测到错误：

- 原始源码测试通过：`original.evaluation.test_pass == true`
- 错误代码测试失败：`buggy.evaluation.test_pass == false`

## 统计结果

| 项目 | 总测试目标 | 原始源码通过 | 错误代码失败 | 检测数 | 检测比例（总目标） | 检测比例（源码通过目标） |
|---|---:|---:|---:|---:|---:|---:|
| ofdrw | 2 | 0 | 0 | 0 | 0.00% | — |
| parquet | 3 | 1 | 0 | 0 | 0.00% | 0.00% |
| thymeleaf | 9 | 4 | 1 | 1 | 11.11% | 25.00% |
| twelvemonkeys | 9 | 4 | 2 | 0 | 0.00% | 0.00% |
| **总计** | **23** | **9** | **3** | **1** | **4.35%** | **11.11%** |

## 结论

- 按全部 23 个生成测试目标计算，错误检测比例为 **1/23 = 4.35%**。
- 只把原始源码测试通过的 9 个目标作为有效分母时，检测比例为 **1/9 = 11.11%**。
- 唯一成功检测到错误的是 Thymeleaf 的 `build` 方法。
- TwelveMonkeys 中有 2 个 buggy 测试失败，但对应的原始源码测试本身也失败，因此不计入严格的错误检测数。
