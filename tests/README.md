# 测试

```sh
.venv/bin/python tests/run_all.py            # 全部
.venv/bin/python tests/run_all.py eval       # 只跑名字含 eval 的
.venv/bin/python tests/test_eval_modes.py    # 单个模块（VERBOSE=1 打印每项详情）
```

**不依赖 pytest**——纯标准库。本仓运行时依赖已经很克制，测试不该拖进新依赖。

## 约定

- **一律用临时库**，绝不碰 `platform.db`（那是线上数据）
- 每个模块在**独立子进程**里跑：`app` 是模块级单例，同进程反复初始化会互相污染
- 功能测试关掉 `WTF_CSRF_ENABLED`；CSRF 本身由专项用例验证
- 改 `Config` 的覆盖项**必须通过 `boot.temp_app(KEY=值)` 传**——
  `app.config.from_object(Config)` 在导入 app 时就快照了，之后再改 `config.Config` 无效。
  这个坑踩过一次：`PER_CASE_TIMEOUT` 设晚了，死循环用例从 `timeout` 变成 `runtime_error`

## 模块

| 文件 | 覆盖 | 项数 |
|---|---|---|
| `test_auth_reset.py` | 找回密码：防枚举、令牌哈希/一次性/过期、限频、锁定解除 | 26 |
| `test_scoring_dynamic.py` | 动态基准：全场最优、并列公平、黑马拉低基准、旧格式回退 | 9 |
| `test_eval_scale.py` | 规模分级 + 逐点计分：三题参考解满分、逐点独立、逐点 baseline | 10 |
| `test_eval_modes.py` | 评测失败模式：编译错/越界/超时/写死答案/不含评测的题 | 13 |
| `test_submit_flow.py` | 提交流程：上传与粘贴、后缀/配额/限流、结果页、榜单 | 21 |

共 **79** 项。

## 加新测试

在 `tests/` 下建 `test_xxx.py`，骨架：

```python
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap as boot
from _bootstrap import check

app, _TMP = boot.temp_app()          # 需要 app 时才建；纯逻辑测试可省
# ... 断言 ...
boot.finish('模块名')
```

`run_all.py` 按文件名自动发现（`test_*.py`），不需要注册。

## 这些测试抓到过什么

它们不是摆设，以下都是**真实被它们抓出来**的：

- 提交间隔限流的**检查顺序**放错（无效提交也被罚等 2 分钟）
- 结果页显示的是**动态基准分**、与评测快照分不同（断言写死数值就会挂）
- 题面 20 处**过时措辞**（还写着固定尺寸）
- `SIGXCPU` 被判成 `runtime_error` 而非 `timeout`（取决于墙钟与 CPU 限额谁先生效，不稳定）
