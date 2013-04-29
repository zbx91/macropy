import re

from macropy.core.macros import *
from macropy.core.lift import macros, q, u
from macropy.macros.adt import case, NO_ARG
import re
from collections import defaultdict
macros = True

@block_macro
def peg(tree):
    for statement in tree.body:
        if type(statement) is Assign:
            new_tree, bindings = parser(statement.value)
            statement.value = q%(Lazy(lambda: ast%new_tree))


    print unparse(tree.body)
    return tree.body


@expr_macro
def peg(tree):
    new_tree, bindings = parser(tree)
    return new_tree

class Substituter(Walker):
    def __init__(self, bindings):
        self.autorecurse = True
        self.bindings = bindings
        def rec(tree):
            if type(tree) is Name and tree.id in self.bindings:
                return q%bindings[u%tree.id]
            else:
                return tree

        self.func = rec

def parser(tree):

    if type(tree) is Str:
        return q%Raw(ast%tree), set()

    if type(tree) is UnaryOp:
        (tree.operand, bindings) = parser(tree.operand)
        return tree, bindings

    if type(tree) is BinOp and type(tree.op) is RShift:
        tree.left, b_left = parser(tree.left)
        tree.right = q%(lambda bindings: ast%Substituter(b_left).recurse(tree.right))
        return tree, b_left

    if type(tree) is BinOp and type(tree.op) is Mult:
        tree.left, b_left = parser(tree.left)
        return tree, b_left

    if type(tree) is BinOp:
        tree.left, b_left  = parser(tree.left)
        tree.right, b_right = parser(tree.right)
        return tree, b_left | b_right

    if type(tree) is Tuple:
        result = q%Seq([])
        result.args[0].elts, bindings = zip(*map(parser, tree.elts))
        result.args[0].elts = list(result.args[0].elts)
        return result, {x for y in bindings for x in y}

    if type(tree) is Call:
        tree.args, arg_bindings = zip(*map(parser, tree.args))
        tree.args = list(tree.args)
        tree.func, func_bindings = parser(tree.func)

        return tree, func_bindings | {x for y in arg_bindings for x in y}

    if type(tree) is Attribute:
        tree.value, bindings = parser(tree.value)
        return tree, bindings

    if type(tree) is Compare and type(tree.ops[0]) is Is:
        left_tree, bindings = parser(tree.left)
        new_tree = q%((ast%left_tree).bind_to(u%tree.comparators[0].id) )
        return new_tree, {tree.comparators[0].id} | bindings



    return tree, set()

"""
PEG Parser Atoms
================
Sequence: e1 e2             ,   8       Seq
Ordered choice: e1 / e2     |   7       Or
Zero-or-more: e*            ~   13      Rep
One-or-more: e+             +   13      rep1
Optional: e?                            opt
And-predicate: &e           &   9       And
Not-predicate: !e           -   13      Not
"""

@case
class Input(string, index):
    pass

@case
class Parser:

    def bind_to(self, string):
        return Binder(self, string)

    def parse(self, string):
        res = self.parse_input(Input(string, 0))
        if res is None:
            return None

        out, bindings, remaining_input = res
        return [out]

    def parse_all(self, string):
        res = self.parse_input(Input(string, 0))
        if res is None:
            return None

        (out, bindings, remaining_input) = res
        if remaining_input.index != len(string):
            return None

        return [out]


    def __and__(self, other):   return And([self, other])

    def __or__(self, other):    return Or([self, other])

    def __neg__(self):          return Not(self)

    def __pos__(self):          return rep1(self)

    def __invert__(self):       return Rep(self)

    def __mul__(self, other):   return Transform(self, other)

    def __pow__(self, other):   return Transform(self, lambda x: other(*x))

    def __rshift__(self, other): return TransformBound(self, other)


    class Raw(string):
        def parse_input(self, input):
            if input.string[input.index:].startswith(self.string):
                return self.string, {}, input.copy(index = input.index + len(self.string))
            else:
                return None

    class Regex(regex_string):
        def parse_input(self, input):
            match = re.match(self.regex_string, input.string[input.index:])
            if match:
                group = match.group()
                return group, {}, input.copy(index = input.index + len(group))
            else:
                return None

    class NChildParser:
        class Seq(children):
            def parse_input(self, input):
                current_input = input
                results = []
                result_dict = defaultdict(lambda: [])
                for child in self.children:
                    res = child.parse_input(current_input)
                    if res is None: return None

                    (res, bindings, current_input) = res
                    results.append(res)
                    for k, v in bindings.items():
                        result_dict[k] = v

                return (results, result_dict, current_input)


        class Or(children):
            def parse_input(self, input):
                for child in self.children:
                    res = child.parse_input(input)
                    if res != None: return res

                return None

        class And(children):
            def parse_input(self, input):
                results = [child.parse_input(input) for child in self.children]
                if all(results):
                    return results[0]

                return None

    class OneChildParser:
        class Not(parser):
            def parse_input(self, input):
                if self.parser.parse_input(input):
                    return None
                else:
                    return (None, {}, input)


        class Rep(parser):
            def parse_input(self, input):
                current_input = input
                results = []
                result_dict = defaultdict(lambda: [])

                while True:
                    res = self.parser.parse_input(current_input)
                    if res is None: return (results, result_dict, current_input)

                    (res, bindings, current_input) = res

                    for k, v in bindings.items():
                        result_dict[k] = result_dict[k] + [v]

                    results.append(res)

        class Transform(parser, func):

            def parse_input(self, input):
                result = self.parser.parse_input(input)
                if result is None:
                    return None
                else:
                    res, bindings, new_input = result
                    return self.func(res), bindings, new_input

        class TransformBound(parser, func):

            def parse_input(self, input):
                result = self.parser.parse_input(input)
                if result is None:
                    return None
                else:
                    res, bindings, new_input = result
                    return self.func(bindings), {}, new_input

        class Binder(parser, name):
            def parse_input(self, input):
                result = self.parser.parse_input(input)
                if result is None: return None
                result, bindings, new_input = result
                bindings[self.name] = result
                return result, bindings, new_input

        class Lazy(parser_thunk):
            def parse_input(self, input):
                if not isinstance(self.parser_thunk, Parser):
                    self.parser_thunk = self.parser_thunk()
                return self.parser_thunk.parse_input(input)


    class Success(string):
        def parse_input(self, input):
            return (self.string, {}, input)


    class Failure():
        def parse_input(self, input):
            return None




def rep1(parser):
    return And([Rep(parser), parser])

def opt(parser):
    return Or([parser, Raw("")])

def r(parser):
    return Regex(parser.string)