
# multi_parser.py
import tree_sitter_languages
from tree_sitter import Parser

# 使用 tree_sitter_languages 获取语言
# PY_LANGUAGE = tree_sitter_languages.get_language('python')
# JAVA_LANGUAGE = tree_sitter_languages.get_language('java')
# RUST_LANGUAGE = tree_sitter_languages.get_language('rust')
# JS_LANGUAGE = tree_sitter_languages.get_language('javascript')


def create_parser(language_name):
    parser = Parser()
    parser.set_language(tree_sitter_languages.get_language(language_name))
    return parser

python_parser = create_parser('python')
java_parser = create_parser('java')
rust_parser = create_parser('rust')
js_parser = create_parser('javascript')




# from tree_sitter import Language, Parser

# import tree_sitter_python
# import tree_sitter_java
# import tree_sitter_javascript


# LANGUAGE_MODULES = {
#     "python": tree_sitter_python,
#     "java": tree_sitter_java,
#     "javascript": tree_sitter_javascript,
# }


# def create_parser(language_name: str) -> Parser:
#     """Create a Tree-sitter parser using the modern API."""
#     name = language_name.lower()

#     if name not in LANGUAGE_MODULES:
#         raise ValueError(f"Unsupported language: {language_name}")

#     grammar = LANGUAGE_MODULES[name]
#     language = Language(grammar.language())

#     return Parser(language)


# python_parser = create_parser("python")
# java_parser = create_parser("java")
# javascript_parser = create_parser("javascript")






# # # multi_parser.py
# # import tree_sitter_languages
# # from tree_sitter import Parser


# # def create_parser(language_name):
# #     parser = Parser()
# #     parser.set_language(tree_sitter_languages.get_language(language_name))
# #     return parser

# # python_parser = create_parser('python')
# # java_parser = create_parser('java')
# # rust_parser = create_parser('rust')
# # js_parser = create_parser('javascript')
