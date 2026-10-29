import os
import openai
from openai import OpenAI
from llm_config import LLMConfig
import logging
import re

logger = logging.getLogger(__name__)

class TestGenerationAgent:
    def __init__(self, llm_config: LLMConfig):
        self.llm_config = llm_config
        self.client = OpenAI(api_key=self.llm_config.API_KEY, base_url=self.llm_config.API_ENDPOINT)
        self.model = self.llm_config.MODEL_NAME

    def init_test_prompt(self, erroneous_code: str, function_info: dict) -> str:
        system_prompt = """You are a professional test engineer specializing in writing high-quality unit test code"""

        function_name = function_info['name']
        function_code = function_info['code']
        # signature = function_code.split(':\n')[0]
        signature = function_code.split('{', 1)[0].rstrip()
        print(signature)

        # match = re.search(r'^def\s+\w+\([^)]*\)(?:\s*->\s*[^:]+)?:', function_code, re.MULTILINE)
        # if match:
        #     signature = match.group(0)

        class_name = None
        class_info = {}
        if function_info['type'] == "method":
            class_name = function_info.get('class_name')
            class_info['class_name'] = class_name
            if function_info['class_constructor']:
                class_info['class_constructor'] = function_info['class_constructor']
            if function_info['class_fields']:
                class_info['class_fields'] = function_info['class_fields']
            # if function_info['class_variables']:
            #     class_info['class_variables'] = function_info['class_variables']

        # specification = function_info['specification']
        file_path = function_info['src_file']
        test_path = function_info['test_file']

#         user_prompt = f"""
# Please generate a test class for the following function.

# Function Information:
# - Src file: {file_path}
# - Function name: {function_name}
# - Class: {class_info if class_name else 'Standalone function'}
# - Is async: {function_info.get('is_async', False)}

# Function Code:
# ```java
# {erroneous_code}
# ```

# Requirements:
# Use JUnit 4 framework for writing tests.
# Your job is to output a corresponding test class that focuses on detecting errors and unexpected behaviors in the code under test.
# The test code should be written into {test_path}. Please make sure the imports are correct.
# Return ONLY code without explanations, non-code text, or markdown formatting.

# ```java
# <test code>
# ```
# """   
        user_prompt = f"""
Instruction:

Your task is to generate test suite to detect and capture mutants in a given method.
Follow these steps to ensure comprehensive and detection for mutants:

1. **Analyze the Method and Its Mutation**:
   - Clearly identify the method's parameters, return type, and intended functionality.
   - Examine the mutated code carefully to determine how the functionality has changed. For example, if a loop condition changes from <= to <, thoroughly consider how the loop's boundary behavior is impacted.
   - Deeply consider any called methods whose implementations are not shown. These methods may alter object states or variables more significantly than initially expected.

2. **Design Test Cases to Capture the Mutant**:
   - Develop test cases targeted specifically at capturing the behavior altered by the mutation. Clearly define the intended behavior of the original method, then contrast this with how the mutation affects outcomes.
   - Include scenarios covering typical usage, edge cases, and boundary conditions relevant to the mutation.
   - Ensure your test cases explicitly address logical differences introduced by the mutation, such as altered loop boundaries, modified exception handling, or changes in data processing logic.

3. **Implement the Test Suite**:
   - Make Sure your variables are declared inside your test Suite.
   - Write a test method annotated with @Test for each test case.
   - Use assertions (e.g., assertEquals, assertTrue) to verify the expected outcomes, ensuring that the test cases catch the mutated behavior.
   - Make sure the test is clear, logical, and thorough.


Your Task:

Given the following method and its mutation, generate a test suite that thoroughly tests the method and detect the mutant. Utilize your reasoning ability to ensure that all possible scenarios and edge cases are considered.

_Input Method ({function_name})_:
```java
{function_code}
```

Method Context:
- Src file: {file_path}
- Class: {class_info if class_name else 'Standalone function'}
- Is async: {function_info.get('is_async', False)}

_Mutation:
```java
{erroneous_code}
```


_Guidelines_:

- **Annotations**: Use @Test to annotate each test method.
- **Assertions**: Use appropriate assertions to validate expected outcomes and catch the mutant.
- **Completeness**: You should complete every assertions on your own, I would not add anything to your code. The test code should be written into {test_path}. Please make sure the imports are correct.
- **Exception Handling**: Ensure that methods throwing exceptions are properly tested.
- **Thinking Step by Step**:
   - Understand the effect of the mutant on the code's logic and structure.
   - Organize the test cases logically within the test suite, ensuring readability and clarity.
   - Keep the test cases small, focused, and meaningful.

- **Version Of Java and Junit**:
   - Use Java 8 and JUnit 4.
   - Use @Test to mark your test methods and ensure that the test cases are correctly structured and implemented.


_Output Format_:
Return ONLY code without explanations, non-code text, or markdown formatting.
```java
<test code>
```
"""

        message = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                    ]
        # return message
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=message,
                temperature=0.7, # Higher temperature for more creative tests
                max_tokens=16384
            )
            test_code = response.choices[0].message.content.strip()
            # Ensure we only get Java code block if LLM adds markdown
            if test_code.startswith("```java") and test_code.endswith("```"):
                test_code = test_code[len("```java"):-len("```")].strip()
            return test_code
        except Exception as e:
            logger.error(f"Error calling LLM for test generation: {e}")
            return "" # Return empty string on error


    def enhance_test_prompt(self, erroneous_code: str, function_info: dict, test: str) -> str:
        system_prompt = """You are a professional test engineer specializing in writing high-quality unit test code"""

        function_name = function_info['name']
        function_code = function_info['code']
        # signature = function_code.split(':\n')[0]
        signature = function_code.split('{', 1)[0].rstrip()
        print(signature)

        # match = re.search(r'^def\s+\w+\([^)]*\)(?:\s*->\s*[^:]+)?:', function_code, re.MULTILINE)
        # if match:
        #     signature = match.group(0)

        class_name = None
        class_info = {}
        if function_info['type'] == "method":
            class_name = function_info.get('class_name')
            class_info['class_name'] = class_name
            if function_info['class_constructor']:
                class_info['class_constructor'] = function_info['class_constructor']
            if function_info['class_fields']:
                class_info['class_fields'] = function_info['class_fields']
            # if function_info['class_variables']:
            #     class_info['class_variables'] = function_info['class_variables']

        # specification = function_info['specification']
        file_path = function_info['src_file']
        test_path = function_info['test_file']

#         user_prompt = f"""
# Please generate a test class for the following function.

# Function Information:
# - Src file: {file_path}
# - Function name: {function_name}
# - Class: {class_info if class_name else 'Standalone function'}
# - Is async: {function_info.get('is_async', False)}

# Function Code:
# ```java
# {erroneous_code}
# ```

# Existing Test Code:
# ```java
# {test}
# ```

# Requirements:
# Use JUnit 4 framework for writing tests.
# Your job is to output a corresponding test class that focuses on detecting errors and unexpected behaviors in the code under test.
# The testcases must be different from the existing test code.
# The test code should be written into {test_path}. Please make sure the imports are correct.
# Return ONLY code without explanations, non-code text, or markdown formatting.

# ```java
# <test code>
# ```
# """

        user_prompt = f"""
Instruction:

Your task is to generate test suite to detect and capture mutants in a given method.
Follow these steps to ensure comprehensive and detection for mutants:

1. **Analyze the Method and Its Mutation**:
   - Clearly identify the method's parameters, return type, and intended functionality.
   - Examine the mutated code carefully to determine how the functionality has changed. For example, if a loop condition changes from <= to <, thoroughly consider how the loop's boundary behavior is impacted.
   - Deeply consider any called methods whose implementations are not shown. These methods may alter object states or variables more significantly than initially expected.

2. **Design Test Cases to Capture the Mutant**:
   - Develop test cases targeted specifically at capturing the behavior altered by the mutation. Clearly define the intended behavior of the original method, then contrast this with how the mutation affects outcomes.
   - Include scenarios covering typical usage, edge cases, and boundary conditions relevant to the mutation.
   - Ensure your test cases explicitly address logical differences introduced by the mutation, such as altered loop boundaries, modified exception handling, or changes in data processing logic.

3. **Implement the Test Suite**:
   - Make Sure your variables are declared inside your test Suite.
   - Write a test method annotated with @Test for each test case.
   - Use assertions (e.g., assertEquals, assertTrue) to verify the expected outcomes, ensuring that the test cases catch the mutated behavior.
   - Make sure the test is clear, logical, and thorough.


Your Task:

Given the following method and its mutation, generate a test suite that thoroughly tests the method and detect the mutant. Utilize your reasoning ability to ensure that all possible scenarios and edge cases are considered.

_Input Method ({function_name})_:
```java
{function_code}
```

Method Context:
- Src file: {file_path}
- Class: {class_info if class_name else 'Standalone function'}
- Is async: {function_info.get('is_async', False)}

_Mutation:
```java
{erroneous_code}
```

_Existing Test Code:
```java
{test}
```

_Guidelines_:

- **Annotations**: Use @Test to annotate each test method.
- **Assertions**: Use appropriate assertions to validate expected outcomes and catch the mutant.
- **Completeness**: You should complete every assertions on your own, I would not add anything to your code. The test code should be written into {test_path}. Please make sure the imports are correct.
- **Different Test Cases**: Ensure that the generated test cases are different from the existing test code.
- **Exception Handling**: Ensure that methods throwing exceptions are properly tested.
- **Thinking Step by Step**:
   - Understand the effect of the mutant on the code's logic and structure.
   - Organize the test cases logically within the test suite, ensuring readability and clarity.
   - Keep the test cases small, focused, and meaningful.

- **Version Of Java and Junit**:
   - Use Java 8 and JUnit 4.
   - Use @Test to mark your test methods and ensure that the test cases are correctly structured and implemented.


_Output Format_:
Return ONLY code without explanations, non-code text, or markdown formatting.
```java
<test code>
```
"""

        message = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                    ]
        # return message
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=message,
                temperature=0.7, # Higher temperature for more creative tests
                max_tokens=16384
            )
            test_code = response.choices[0].message.content.strip()
            # Ensure we only get Java code block if LLM adds markdown
            if test_code.startswith("```java") and test_code.endswith("```"):
                test_code = test_code[len("```java"):-len("```")].strip()
            return test_code
        except Exception as e:
            logger.error(f"Error calling LLM for test generation: {e}")
            return "" # Return empty string on error

    def fix_test_prompt(self, test: str, error: str) -> str:
        prompt = f"""The tests below are failing with the following error message:
        Tests:
        ```java
        {test}
        ```

        Error:
        ```
        {error}
        ```

        Please provide a corrected version of the test code that addresses the error.
        ```java
        <corrected test code>
        ```
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": "You are a helpful assistant that fixes failing test code."},
                          {"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=16384
            )
            fixed_test_code = response.choices[0].message.content.strip()
            # Ensure we only get Java code block if LLM adds markdown
            if fixed_test_code.startswith("```java") and fixed_test_code.endswith("```"):
                fixed_test_code = fixed_test_code[len("```java"):-len("```")].strip()
            return fixed_test_code
        except Exception as e:
            logger.error(f"Error calling LLM for test fixing: {e}")
            return test # Return original test code on error

    


if __name__ == "__main__":
    # Example usage (will require actual API key and endpoint)
    llm_config_instance = LLMConfig(api_key=os.getenv("LLM_API_KEY", "YOUR_LLM_API_KEY"),
                                    api_endpoint=os.getenv("LLM_API_ENDPOINT", "https://api.apiyi.com/v1"),
                                    model_name=os.getenv("LLM_MODEL_NAME", "gpt-4o-mini"))

    agent = TestGenerationAgent(llm_config=llm_config_instance)
    sample_original_code = """
def add(a, b):
    return a + b
"""
    sample_buggy_code = """
def add(a, b):
    return a - b # Bug: should be a + b
"""
    print("原始代码:\n", sample_original_code)
    print("错误代码:\n", sample_buggy_code)

    # To run this, you'll need to set LLM_API_KEY environment variable
    # generated_tests = agent.generate_tests(sample_original_code, sample_buggy_code)
    # if generated_tests:
    #     print("\n生成的测试:\n", generated_tests[0])
    #     agent.integrate_with_execution_environment(generated_tests, {"test_output_dir": "./output_tests"})

    agent.integrate_with_execution_environment([], {"test_output_dir": "./output_tests"}) # Example to create dir
