#!/usr/bin/env python3
import re
import sys
import os

def delete_failed_tests(log_path):
    if not os.path.isfile(log_path):
        print(f"日志文件不存在: {log_path}")
        return

    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    # 匹配 [ERROR] 后跟文件路径（直到 .java 和冒号）
    pattern = re.compile(r'^\[ERROR\]\s+([^:]+\.java):')

    file_set = set()
    for line in lines:
        line = line.rstrip()
        m = pattern.match(line)
        if m:
            file_path = m.group(1)
            file_set.add(file_path)

    if not file_set:
        print("未找到编译错误文件。")
        # 调试：打印所有 [ERROR] 行
        for line in lines:
            if '[ERROR]' in line:
                print(line.rstrip())
        return

    print(f"发现 {len(file_set)} 个编译失败的文件：")
    for file_path in sorted(file_set):
        print(f"  {file_path}")
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"    已删除")
        else:
            print(f"    文件不存在，尝试查找 basename...")
            base = os.path.basename(file_path)
            found = []
            for root, _, files in os.walk('/testbed'):
                if base in files:
                    found.append(os.path.join(root, base))
            if found:
                for f in found:
                    print(f"    找到 {f}，删除？")
                    # 如果需要自动删除第一个，可取消下一行注释
                    # os.remove(f); print("    已删除")
            else:
                print("    未找到")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python delete_failed_tests.py <compile.log路径>")
        sys.exit(1)
    delete_failed_tests(sys.argv[1])