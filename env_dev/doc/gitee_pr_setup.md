# OpenChipFlow Gitee PR Setup (env note)

## 目的
记录 OpenChipFlow 在本机上可复用的 Gitee PR 配置方式，供后续环境迁移与排障参考。

参考来源：`~/work/verilog_sim_template` 中已验证的 Gitee CLI + Token 方案。

---

## 1) 安装 gitee CLI（与 verilog_sim_template 对齐）

```bash
npm install -g @jj-h/gitee@latest
```

验证：

```bash
gitee --version
gitee pr --help
```

---

## 2) 配置 token（推荐脚本）

脚本位置：

```bash
env_dev/script/setup-gitee-token.sh
```

执行：

```bash
bash env_dev/script/setup-gitee-token.sh
```

脚本会写入 `~/.gitee/config.yml`，并校验：

- `gitee --version`
- `gitee pr create --help`

---

## 3) 手动创建 PR（命令模板）

```bash
gitee pr create \
  -t "<PR title>" \
  -B master \
  -H <feature-branch> \
  -b "<PR body>"
```

常见前置：

```bash
git remote -v
git branch --show-current
git push -u origin <feature-branch>
```

---

## 4) 常见失败与修复

1. `gitee pr create` 报找不到分支
   - 先 `git push -u origin <feature-branch>`

2. `gitee` 命令存在但 `pr` 子命令不可用
   - 确认安装的是 `@jj-h/gitee`，不是同名其他 npm 包
   - 重新安装：`npm install -g @jj-h/gitee@latest`

3. 配置文件异常
   - 检查 `~/.gitee/config.yml` 是否为 YAML 且 token 有效
   - 重新运行脚本：`bash env_dev/script/setup-gitee-token.sh`

---

## 5) 与 pipeline 的联动

`cocotb_ex/ai_cli_pipeline/prompts/pr_submit.txt` 已按本方案更新为：

- `gitee pr create -t ... -B master -H <current_branch> -b ...`

这样可以减少在 Gitee 上因 base/head 未指定导致的失败。

---

## 6) 本次执行记录（供后续复用）

- 时间：2026-02-17
- 分支：`feature/env-gitee-pr-setup`
- PR：`https://gitee.com/your_org/open-chip-flow/pulls/1`
- 结果：`gitee pr create` 一次成功，无需重试修复。