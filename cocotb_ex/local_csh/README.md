# 本地 Ubuntu 切换到 csh/tcsh（给 cocotb_ex 使用）

本目录用于把本机交互环境从 bash 切到 csh/tcsh，并提供一个可用的 `~/.cshrc` 示例。

> 推荐用 `tcsh`（比传统 `csh` 更常见/更好用），但两者语法兼容度较高。

## 1) 安装 shell

确认当前是否已有 `tcsh`：

```bash
command -v tcsh || true
grep -nE "tcsh|csh" /etc/shells || true
```

如未安装（需要 apt 网络/源）：

```bash
sudo apt update
sudo apt install -y tcsh
```

## 2) 生成/安装 `~/.cshrc`

将示例拷贝到家目录：

```bash
cp -v cocotb_ex/local_csh/cshrc.example ~/.cshrc
```

建议把密钥类环境变量放在单独文件，避免误入库：

```csh
if ( -f "$HOME/.cshrc_secrets" ) source "$HOME/.cshrc_secrets"
```

然后在 `~/.cshrc_secrets` 里写（示例）：

```csh
setenv GEMINI_API_KEY "<your_key_here>"
```

## 3) 先在当前会话试运行（不改默认 shell）

说明：

- 交互式启动 `tcsh` 时会**自动**执行 `~/.cshrc`，不需要再手工 `source ~/.cshrc`
- 不要在 bash 里执行 `source ~/.cshrc`（bash 解析 csh 语法会报错）；要么进入 `tcsh`，要么用 `tcsh -c '...'`

推荐两种验证方式（二选一）：

```bash
# 方式 A：进入交互 tcsh（会自动 source ~/.cshrc）
tcsh
echo $SHELL
echo $PATH

# 方式 B：从 bash 一次性验证（执行完即退出）
# 注意：非交互 tcsh 下默认没有 $prompt 变量，而 ~/.cshrc 常用 `if ( $?prompt )` 保护；
# 因此这里先手工 set 一个 prompt，让 ~/.cshrc 的交互配置生效。
tcsh -f -c 'set prompt=">"; source ~/.cshrc; echo $SHELL; echo $PATH'
```

确认 `PATH/alias/cd` 等行为符合预期后，再改默认 shell。

## 4) 修改默认登录 shell

```bash
chsh -s "$(command -v tcsh)"
```

重新登录后生效。

## 回滚方式

- 临时回到 bash：在 csh/tcsh 里执行 `bash`
- 恢复默认 shell：`chsh -s /bin/bash`
- 禁用自定义：`mv ~/.cshrc ~/.cshrc.bak`
