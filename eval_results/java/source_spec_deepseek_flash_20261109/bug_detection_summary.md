# Bug Detection Summary

评测目录：`eval_results/java/source_spec_deepseek_flash_20261109`

## 判定口径

逐个目标配对 `original/evaluated_results.json` 与 `buggy/evaluated_results.json`。只有同时满足以下条件才算测试检测到错误：

- 原始源码测试通过：`original.evaluation.test_pass == true`
- 错误代码测试失败：`buggy.evaluation.test_pass == false`

## 统计结果

| 项目 | 总测试目标 | 原始源码通过 | 错误代码失败 | 检测数 | 检测比例（总目标） | 检测比例（源码通过目标） |
|---|---:|---:|---:|---:|---:|---:|
| ofdrw | 2 | 2 | 0 | 0 | 0.00% | 0.00% |
| parquet | 3 | 3 | 0 | 0 | 0.00% | 0.00% |
| thymeleaf | 9 | 9 | 5 | 5 | 55.56% | 55.56% |
| twelvemonkeys | 9 | 9 | 4 | 4 | 44.44% | 44.44% |
| **总计** | **23** | **23** | **9** | **9** | **39.13%** | **39.13%** |

## 结论

- 全部 23 个生成测试目标的原始源码均通过。
- 其中 9 个测试能够使错误代码失败，因此错误检测比例为 **9/23 = 39.13%**。
- 由于所有原始源码测试均通过，按“原始源码通过目标”作为分母时比例同样为 **9/23 = 39.13%**。
- Thymeleaf 检测到 5 个错误，TwelveMonkeys 检测到 4 个错误；ofdrw 和 parquet 均未检测到错误。
