import json


file_path = "test_results/java/flink/junit5_agent/copilot_testgen_results.json"
with open(file_path, "r") as f:
    data = json.load(f)

time = 0
for entry in data:
    time += entry.get("time", 0)

print(f"avg time: {time / len(data):.2f}s  total time: {time:.2f}s  count: {len(data)}")