# Repo Agent Guide

本仓库包含多个 Verilog/cocotb 仿真模板，其中 `cocotb_vcs/` 会被移植到**无网络**的目标环境。

## 目标环境假设（cocotb_vcs）

- 目标环境无外网。
- 目标环境已有 EDA 工具：Synopsys `vcs` 与 `verdi`（含 license 配置）。
- Python 依赖需要提前准备为离线 wheel 包。

## Docker（复现内网/离线环境）

使用 ManyLinux 2014 base image 在本机复现目标环境，并在其中准备离线依赖。

**Docker run（原始命令，需保持可复现）：**

```bash
docker run --hostname=0450485939d6 --env=PATH=/opt/rh/devtoolset-10/root/usr/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin --env=AUDITWHEEL_ARCH=x86_64 --env=LC_ALL=en_US.UTF-8 --env=LANG=en_US.UTF-8 --env=LANGUAGE=en_US.UTF-8 --env=DEVTOOLSET_ROOTPATH=/opt/rh/devtoolset-10/root --env=SSL_CERT_FILE=/opt/_internal/certs.pem --env=AUDITWHEEL_POLICY=manylinux2014 --env=AUDITWHEEL_PLAT=manylinux2014_x86_64 --env=LD_LIBRARY_PATH=/opt/rh/devtoolset-10/root/usr/lib64:/opt/rh/devtoolset-10/root/usr/lib:/opt/rh/devtoolset-10/root/usr/lib64/dyninst:/opt/rh/devtoolset-10/root/usr/lib/dyninst:/usr/local/lib64 --env=PKG_CONFIG_PATH=/usr/local/lib/pkgconfig --volume=/home/user/work/verilog_sim_template:/data --network=bridge --workdir=/ --restart=no --label='desktop.docker.io/wsl-distro=Ubuntu-22.04' --label='maintainer=The ManyLinux project' --label='org.label-schema.build-date=20251110' --label='org.label-schema.license=GPLv2' --label='org.label-schema.name=ManyLinux 2014 Base Image' --label='org.label-schema.schema-version=1.0' --label='org.label-schema.vendor=The ManyLinux project' --label='org.opencontainers.image.created=2025-11-10 00:00:00+00:00' --label='org.opencontainers.image.licenses=GPL-2.0-only' --label='org.opencontainers.image.title=ManyLinux 2014 Base Image' --label='org.opencontainers.image.vendor=The ManyLinux project' --runtime=runc -t -d quay.io/pypa/manylinux2014_x86_64
```

**卷映射：**宿主机 `/home/user/work/verilog_sim_template` 挂载为容器内 `/data`（因此离线 wheel 目录也可在容器内访问为 `/data/cocotb_offline/wheels_p12/`）。

## cocotb 离线依赖（重要约束）

在 docker 中配置 cocotb 所需环境后：

- 将缺少的 Python wheel 包拷贝到：`/home/user/work/verilog_sim_template/cocotb_offline/wheels_p12/`
- 将新增 wheel 的 hash 信息**追加**到 `wheels_p12.hash` 文件末尾：
  - 必须保持原有格式
  - 不允许删除/重写旧内容，只能在末尾补充
### cocotb 依赖包强制要求（重申）

请按以下要求排查 `cocotb` 及其依赖是否为**兼容范围内的最新版本**，并保证离线环境可完整安装：

1. **必须在 Docker 中执行**（ManyLinux 2014）。
2. **工具链版本固定**：`gcc` 9.2.0；Python 3.12.7。
3. **离线安装验证**：先执行以下命令：
   ```bash
   python -m pip install --no-index --find-links /home/user/work/verilog_sim_template/cocotb_offline/wheels_p12 \
     cocotb==2.0.1 cocotb-bus==0.3.0 cocotb-coverage==2.0 pytest==9.0.2
   ```
   - 安装完成后，确认其余依赖是否都能通过依赖解析自动安装或按需手动安装。
   - 若无法安装，补齐缺失依赖的 wheel 包。
4. **新增 wheel 放置位置**：`/home/user/work/verilog_sim_template/cocotb_offline/wheels_p12/`。
5. **hash 记录**：对每个新增 wheel，将其 hash 以既有格式**追加**到 `wheels_p12.hash` 末尾（禁止覆盖/删除旧内容）。

> **状态标记（内网已就绪）**：`cocotb_vcs/` 的内网环境已完成配置与离线安装验收；后续**不需要每次**重复分析/补齐 wheelhouse 依赖。  
> 仅当出现 wheelhouse 变更（新增/升级包）、切换 Python ABI（如 `cp312` → `cp313`）、或内网离线安装失败时，再按本节流程复查与补齐。

## 复现问题规则：
- 每做一步就把结果追加到 ISSUE.md 的实验记录
- 输出时给出：下一步（含命令）+ 回滚方式
