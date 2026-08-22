import os
import subprocess
import json
import shutil
import tempfile
import time
from config import TEST_DATA_DIR, EVAL_TIMEOUT

# 假设 ScratchV 提供以下接口（实际请替换为真实 API）
# from scratchv import compile_model, run_spike

def run_evaluation(submission_id, team_name, problem_id, code_path):
    """
    执行评测，返回 (score, details_dict)
    """
    # 1. 准备测试用例（根据 problem_id 选择对应的测试输入）
    test_cases = get_test_cases(problem_id)   # 返回列表，每个元素是输入文件路径
    if not test_cases:
        return 0.0, {'error': 'No test cases found'}

    # 2. 编译选手代码（假设 ScratchV 提供编译接口）
    #   选手代码可能是一个 Python 脚本，调用 ScratchV API；也可能是已实现的 pass。
    #   这里假设选手提交的是一个 Python 文件，我们需要执行它来生成 RISC-V 二进制。
    #   实际操作需根据 ScratchV 的使用方式调整。
    binary_path = compile_submission(code_path, problem_id)
    if not binary_path:
        return 0.0, {'error': 'Compilation failed'}

    # 3. 对每个测试用例运行 Spike，收集指令数、周期等
    total_score = 0.0
    details = []
    for idx, test_input in enumerate(test_cases):
        result = run_spike(binary_path, test_input)
        if result['error']:
            details.append({'case': idx, 'error': result['error']})
            continue
        # 计算该用例得分：假设满分 3 分（或根据赛题调整）
        # 性能分数 = baseline_time / player_time，但 baseline 需要预置
        baseline_time = get_baseline_time(problem_id, idx)  # 从配置文件读取
        if baseline_time <= 0:
            score_case = 0.0
        else:
            player_time = result.get('cycles', 0) / (1000*1000)  # 转换为 ms
            score_case = min(1.0, baseline_time / player_time) if player_time > 0 else 0.0
        total_score += score_case * 3.0  # 假设每个用例满分3分
        details.append({
            'case': idx,
            'cycles': result.get('cycles', 0),
            'instructions': result.get('instructions', 0),
            'player_time': player_time,
            'score': score_case
        })

    # 4. 清理临时文件
    if os.path.exists(binary_path):
        os.remove(binary_path)

    return total_score, {'cases': details, 'total_score': total_score}

def get_test_cases(problem_id):
    """返回该题目的所有测试输入文件列表"""
    case_dir = os.path.join(TEST_DATA_DIR, problem_id)
    if not os.path.exists(case_dir):
        return []
    # 假设文件命名为 case_0.in, case_1.in, ...
    cases = []
    i = 0
    while True:
        f = os.path.join(case_dir, f'case_{i}.in')
        if os.path.exists(f):
            cases.append(f)
            i += 1
        else:
            break
    return cases

def get_baseline_time(problem_id, case_idx):
    """读取预置的基线性能数据（单位：秒或周期数）"""
    # 实际应从配置文件或数据库读取
    baseline_file = os.path.join(TEST_DATA_DIR, problem_id, 'baseline.json')
    if os.path.exists(baseline_file):
        with open(baseline_file) as f:
            data = json.load(f)
        return data.get(str(case_idx), 1.0)
    return 1.0  # 默认基线

def compile_submission(code_path, problem_id):
    """
    调用 ScratchV 编译选手代码，生成 RISC-V 可执行文件。
    这里简化：假设选手代码是 Python 脚本，我们执行它并指定输出二进制路径。
    实际应根据 ScratchV 的 API 调整。
    """
    # 创建临时输出目录
    out_dir = tempfile.mkdtemp(prefix='scratchv_')
    binary = os.path.join(out_dir, 'output.bin')

    # 示例：运行选手 Python 脚本，传入参数 --output binary_path
    # 实际选手代码可能需要不同的调用方式，请查阅 ScratchV 文档。
    cmd = ['python3', code_path, '--output', binary, '--problem', problem_id]
    try:
        subprocess.run(cmd, check=True, timeout=30, capture_output=True)
        if os.path.exists(binary) and os.path.getsize(binary) > 0:
            return binary
        else:
            return None
    except Exception as e:
        print(f"Compilation error: {e}")
        return None

def run_spike(binary_path, test_input):
    """使用 Spike 运行二进制，返回性能数据"""
    # Spike 命令示例：spike --isa=RV32IM --extension=Zvfh --cycles binary + test_input
    # 假设测试输入通过标准输入传递
    cmd = ['spike', '--isa=RV64IMAC', '--cycles', binary_path]
    with open(test_input, 'rb') as inf:
        try:
            result = subprocess.run(cmd, stdin=inf, capture_output=True, timeout=EVAL_TIMEOUT)
            # Spike 的输出可能包含性能统计，需要解析
            # 这里简单模拟：假设 Spike 在 stderr 输出 "cycle count: 12345"
            output = result.stderr.decode('utf-8') + result.stdout.decode('utf-8')
            cycles = extract_cycles(output)
            instructions = extract_instructions(output)
            return {'cycles': cycles, 'instructions': instructions, 'error': None}
        except subprocess.TimeoutExpired:
            return {'error': 'Timeout', 'cycles': 0, 'instructions': 0}
        except Exception as e:
            return {'error': str(e), 'cycles': 0, 'instructions': 0}

def extract_cycles(output):
    # 正则或字符串解析 Spike 输出
    import re
    match = re.search(r'cycle\s+count\s*:\s*(\d+)', output, re.I)
    if match:
        return int(match.group(1))
    return 0

def extract_instructions(output):
    import re
    match = re.search(r'instruction\s+count\s*:\s*(\d+)', output, re.I)
    if match:
        return int(match.group(1))
    return 0