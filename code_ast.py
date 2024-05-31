import os
import sys
import Levenshtein
from tree_sitter import Language, Parser


class CustomTreeNode:
    def __init__(self, old_node, new_node):
        self.old_node = old_node
        self.new_node = new_node
        self.children = []

    def add_child(self, child):
        self.children.append(child)
        
    def sexp(self):
        if not self.children:
            return f'({self.node.type} "{self.node.text}")'
        else:
            children_sexp = " ".join(child.sexp() for child in self.children)
            return f'({self.node.type} {children_sexp})'
    
    def __str__(self):
        if self.children == []:
            return self.old_node.text.decode("utf-8")
        children_str = " ".join(str(child) for child in self.children)
        return children_str

def str_similarity(before_window: list[str], after_window: list[str]) -> float:
    str1 = "".join(before_window)
    str2 = "".join(after_window)
    distance = Levenshtein.distance(str1, str2)
    max_len = max(len(str1), len(str2))
    similarity = 1 - (distance / max_len)
    return similarity

def parse(code, language):
    assert language in ["go", "javascript", "typescript", "python", "java"]
    if not os.path.exists("tree-sitter/build/my-languages.so"):
        Language.build_library(
            # Store the library in the `build` directory
            "tree-sitter/build/my-languages.so",

            # Include one or more languages
            [
                "tree-sitter/tree-sitter-go",
                "tree-sitter/tree-sitter-javascript",
                "tree-sitter/tree-sitter-typescript/typescript",
                "tree-sitter/tree-sitter-python",
                "tree-sitter/tree-sitter-java",
            ]
        )
    parser = Parser()
    parser.set_language(Language("tree-sitter/build/my-languages.so", language))
    tree = parser.parse(bytes(code, "utf8"))
    return tree

def max_common_subtree(root1, root2):
    def is_equal(node1, node2):
        if node1.child_count != 0 and node2.child_count != 0:
            return node1.type == node2.type
        elif node1.child_count == 0 and node2.child_count == 0:
            return node1.type == node2.type and node1.text == node2.text
        else:
            return False

    dp = {}

    def dfs(node1, node2):
        if not node1 or not node2:
            return 0, None
        if (node1, node2) in dp:
            return dp[(node1, node2)]

        if is_equal(node1, node2):
            matched = 1
            matched_children = []
            for child1 in node1.children:
                max_match = 0
                best_child_match = None
                for child2 in node2.children:
                    child_match, matched_subtree = dfs(child1, child2)
                    if child_match > max_match:
                        max_match = child_match
                        best_child_match = matched_subtree
                matched += max_match
                if best_child_match:
                    matched_children.append(best_child_match)

            matched_subtree = CustomTreeNode(node1, node2)
            matched_subtree.children = matched_children
        else:
            matched = 0
            matched_subtree = None

        dp[(node1, node2)] = (matched, matched_subtree)
        return dp[(node1, node2)]

    _, result_subtree = dfs(root1, root2)
    return result_subtree

def get_common_position(node, code1, code2):
    """
    Func:
        Get common position of 2 codes based on the max common subtree
        of 2 ASTs
    Args:
        node: CustomTreeNode, the root of the max common subtree
        code1: str, the first code
        code2: str, the second code
    Return:
        common_position: list, the list of common position between 2 codes
            each element is a dict with keys:
                - text: str, the text of the common position
                - old_start_pos: int, the start position of the common position in the first code
                - old_end_pos: int, the end position of the common position in the first code
                - old_lines: list, the list of line indexes of the common position in the first code
                - new_start_pos: int, the start position of the common position in the second code
                - new_end_pos: int, the end position of the common position in the second code
                - new_lines: list, the list of line indexes of the common position in the second code
    """
    def get_line_number(code, start_pos, end_pos):
        line_idxes = []
        code_lines = code.splitlines(keepends=True)
        current_char_idx = 0
        for line_idx, line in enumerate(code_lines):
            line_begin_char_idx = current_char_idx
            line_end_char_idx = current_char_idx + len(line)
            if start_pos < line_end_char_idx and end_pos > line_begin_char_idx:
                line_idxes.append(line_idx)
            current_char_idx = line_end_char_idx
        return line_idxes
    
    if node.children == []:
        # print(f"Text: {node.old_node.text.decode('utf8')}, before_start: {node.old_node.start_byte}, before_end: {node.old_node.end_byte}, after_start: {node.new_node.start_byte}, after_end: {node.new_node.end_byte}")
        old_start_byte = node.old_node.start_byte #if node.old_node.parent is None else node.old_node.parent.start_byte
        old_end_byte = node.old_node.end_byte #if node.old_node.parent is None else node.old_node.parent.end_byte
        new_start_byte = node.new_node.start_byte #if node.new_node.parent is None else node.new_node.parent.start_byte
        new_end_byte = node.new_node.end_byte #if node.new_node.parent is None else node.new_node.parent.end_byte
        old_line_numbers = get_line_number(code1, old_start_byte, old_end_byte)
        new_line_numbers = get_line_number(code2, new_start_byte, new_end_byte)
        if old_line_numbers == [] and new_line_numbers == []:
            return []
        common_position = [{
            "text": node.old_node.text.decode('utf8'),
            "old_start_pos": old_start_byte,
            "old_end_pos": old_end_byte,
            "old_lines": old_line_numbers,
            "new_start_pos": new_start_byte,
            "new_end_pos": new_end_byte,
            "new_lines": new_line_numbers,
        }]
    else:
        common_position = []
        for child in node.children:
            common_position.extend(get_common_position(child, code1, code2))
    return common_position

def merge_matched_position(common_positions):
    """
    Func:
        Given the matched replace blocks, merge the overlapped blocks
    Args:
        common_positions: list, the list of matched replace blocks
    Return:
        merged_positions: list, the list of merged replace blocks
    """
    def is_consecutive(numbers):
        if len(numbers) < 2:
            return True  # 0或1个元素的列表被视为连贯的

        for i in range(1, len(numbers)):
            if numbers[i] != numbers[i - 1] + 1:
                return False
        return True
    
    positions = [(position["old_lines"], position["new_lines"]) for position in common_positions]
    
    merged_positions = [positions[0]]
    for position in positions[1:]:
        to_merge_position_group_idx = []
        for mp_idx, mp in enumerate(merged_positions):
            if len(set(position[0]).intersection(set(mp[0]))) != 0 or len(set(position[1]).intersection(set(mp[1]))) != 0:
                to_merge_position_group_idx.append(mp_idx)
        if to_merge_position_group_idx == []:
            merged_positions.append((position[0], position[1]))
            continue
        to_merge_position = [merged_positions[idx] for idx in to_merge_position_group_idx] + [(position[0], position[1])]
        merged_old_position = list(set([line for lines in to_merge_position for line in lines[0]]))
        sorted_old_position = sorted(merged_old_position)
        merged_new_position = list(set([line for lines in to_merge_position for line in lines[1]]))
        sorted_new_position = sorted(merged_new_position)
        # if idx in sorted_old_position & sorted_new_position is continuous, then merge them
        if is_consecutive(sorted_old_position) and is_consecutive(sorted_new_position):
            merged_positions = [mp for idx, mp in enumerate(merged_positions) if idx not in to_merge_position_group_idx]
            merged_positions.append((sorted_old_position, sorted_new_position))
        else:
            return None # if the merged positions are not continuous, we believe the quality of the matched positions is not good, so we return None

    return merged_positions

def finer_grain_window(before: list[str], after: list[str], lang: str) -> dict:
    new_window = []
    before_str = "".join(before)
    after_str = "".join(after)
    before_tree = parse(before_str, lang)
    after_tree = parse(after_str, lang)
    common_tree = max_common_subtree(before_tree.root_node, after_tree.root_node)
    if common_tree is None:
        return [
            {
                "block_type": "delete",
                "before": before,
                "after": []
            },
            {
                "block_type": "insert",
                "before": [],
                "after": after
            }
        ]
    common_positions = get_common_position(common_tree, before_str, after_str)
    if common_positions == []:
        return [
            {
                "block_type": "delete",
                "before": before,
                "after": []
            },
            {
                "block_type": "insert",
                "before": [],
                "after": after
            }
        ]
    merged_positions = merge_matched_position(common_positions)
    if merged_positions is None:
        raise ValueError("The quality of the matched positions is not good")
    filtered_merged_positions = [merged_positions[0]]
    for match_pos_idx, match_pos in enumerate(merged_positions[1:]):
        match_pos_idx += 1
        if match_pos[0][0] > filtered_merged_positions[-1][0][-1] and \
        match_pos[1][0] > filtered_merged_positions[-1][1][-1]:
            filtered_merged_positions.append(match_pos)
    
    # make a second check to make sure the matched positions are indeed matched
    to_be_filtered_positions = []
    for match_pos in filtered_merged_positions:
        score = str_similarity(before[match_pos[0][0]:match_pos[0][-1]+1], after[match_pos[1][0]:match_pos[1][-1]+1])
        if score < 0.05:
            to_be_filtered_positions.append(match_pos)
    for match_pos in to_be_filtered_positions:
        filtered_merged_positions.remove(match_pos)
    
    if len(filtered_merged_positions) == 0:
        return [
            {
                "block_type": "delete",
                "before": before,
                "after": []
            },
            {
                "block_type": "insert",
                "before": [],
                "after": after
            }
        ]
    for match_pos_idx, match_pos in enumerate(filtered_merged_positions):
        if match_pos_idx == 0:
            prev_old_end_line_idx = -1
            prev_new_end_line_idx = -1
        else:
            prev_old_end_line_idx = filtered_merged_positions[match_pos_idx-1][0][-1]
            prev_new_end_line_idx = filtered_merged_positions[match_pos_idx-1][1][-1]
        # take care of unmatched positions before this matched position
        if prev_old_end_line_idx + 1 < match_pos[0][0] and prev_new_end_line_idx + 1 < match_pos[1][0]:
            new_window.append({
                "block_type": "delete",
                "before": before[prev_old_end_line_idx+1:match_pos[0][0]],
                "after": []
            })
            new_window.append({
                "block_type": "insert",
                "before": [],
                "after": after[prev_new_end_line_idx+1:match_pos[1][0]]
            })
        elif prev_old_end_line_idx + 1 < match_pos[0][0]:
            new_window.append({
                "block_type": "delete",
                "before": before[prev_old_end_line_idx+1:match_pos[0][0]],
                "after": []
            })
        elif prev_new_end_line_idx + 1 < match_pos[1][0]:
            new_window.append({
                "block_type": "insert",
                "before": [],
                "after": after[prev_new_end_line_idx+1:match_pos[1][0]]
            })
        # take care of matched positions
        new_window.append({
            "block_type": "modify",
            "before": before[match_pos[0][0]:match_pos[0][-1]+1],
            "after": after[match_pos[1][0]:match_pos[1][-1]+1]
        })
        # take care of unmatched positions after last matched position
        if match_pos_idx == len(filtered_merged_positions) - 1:
            if match_pos[0][-1] != len(before) - 1 and match_pos[1][-1] != len(after) - 1:
                new_window.append({
                    "block_type": "delete",
                    "before": before[match_pos[0][-1]+1:],
                    "after": []
                })
                new_window.append({
                    "block_type": "insert",
                    "before": [],
                    "after": after[match_pos[1][-1]+1:]
                })
            elif match_pos[0][-1] != len(before) - 1:
                new_window.append({
                    "block_type": "delete",
                    "before": before[match_pos[0][-1]+1:],
                    "after": []
                })
            elif match_pos[1][-1] != len(after) - 1:
                new_window.append({
                    "block_type": "insert",
                    "before": [],
                    "after": after[match_pos[1][-1]+1:]
                })

    totoal_block_before = 0
    totoal_block_after = 0
    for block in new_window:
        totoal_block_before += len(block["before"])
        totoal_block_after += len(block["after"])
    try:
        assert totoal_block_before == len(before)
        assert totoal_block_after == len(after)
    except:
        print(f"Before: {before}, After: {after}")
        raise AssertionError
    
    return new_window
    
    