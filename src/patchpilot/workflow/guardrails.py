"""Deterministic protection for regression expectations."""

import ast


class _V2TestAPIs(ast.NodeTransformer):
    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)
        node.attr = {"model_validate": "parse_obj", "model_dump": "dict"}.get(
            node.attr, node.attr)
        return node


def validate_test_change(original: str, proposed: str) -> None:
    """Allow only v1→v2 API spelling changes in regression tests."""
    old_tree = ast.parse(original)
    new_tree = _V2TestAPIs().visit(ast.parse(proposed))
    if ast.dump(old_tree, include_attributes=False) != ast.dump(new_tree, include_attributes=False):
        raise ValueError("regression test behavior or expectations changed")
