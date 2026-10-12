# 星序应用管理 · Xingxu

Ubuntu 原生桌面应用管理工具。查看应用图标、名称、版本、占用空间和安装日期，快速搜索、筛选，并查看和执行卸载计划。

Native Ubuntu application manager built with Python and GTK 3.

![示例界面](docs/screenshots/main.png)

截图使用示例应用数据，不代表当前电脑的安装记录。

## 功能

- 显示桌面应用，不混入后台依赖库；空间汇总按软件包去重。
- 支持 APT / Debian、Snap、Flatpak 和可确认归属的用户目录独立安装应用。
- 即时搜索应用名或软件包，按来源、最近安装和大型应用筛选。
- 点击名称、版本、占用空间、安装时间旁的小箭头切换升序／降序；与下拉排序同步。未知值始终置后。
- 卸载前展示受影响的软件包或文件清单；执行前重新核对，结束后验证状态，并保留卸载记录。
- 深色界面、高对比排序菜单；Ctrl+F 搜索，Ctrl+R 刷新。

## 下载与安装

从 [GitHub Releases](https://github.com/wanghao9103/xingxu-app-manager/releases/latest) 下载 `miemie-app-manager_1.1.2_all.deb` 和 `SHA256SUMS`，在下载目录执行：

```bash
sha256sum -c SHA256SUMS
sudo apt install ./miemie-app-manager_1.1.2_all.deb
```

在应用菜单搜索「星序应用管理」，或运行 `miemie-app-manager`。

本版桌面实测环境为 **Ubuntu 26.04.1 amd64**。安装包架构标记为 `all`，使用系统 Python 和 GTK，其他发行版及硬件架构的实际桌面运行尚未覆盖。依赖包含 Python 3.10+、PyGObject、GTK 3、APT/dpkg 和 pkexec；Snap、Flatpak 仅在已安装对应管理器时使用。

## 从源码运行

```bash
git clone https://github.com/wanghao9103/xingxu-app-manager.git
cd xingxu-app-manager
sudo apt install python3-gi gir1.2-gtk-3.0 librsvg2-common pkexec
./scripts/start.sh
```

也可以安装到当前用户的应用菜单，无需管理员权限：

```bash
/usr/bin/python3 scripts/install-user.py
```

用户版存放在 `~/.local/share/miemie-app-manager`。从用户版切换到系统安装包时，移除旧的 `~/.local/share/applications/io.miemie.AppManager.desktop` 用户入口，避免覆盖系统入口。

## 数据来源与卸载边界

- 应用入口来自 Gio。APT 使用 `.desktop` 文件或实际程序的 dpkg 归属，只接收已安装状态的软件包。版本和安装大小来自 dpkg。
- APT 安装日期来自留存的 dpkg 日志，兼容 gzip 轮转记录；升级不覆盖最初安装日期。记录不足时显示「未知」，不会用文件修改日期代替。
- Snap 大小为当前 `.snap` 镜像大小。Flatpak 区分用户级和系统级；未可靠取得的大小与日期显示未知。
- 独立安装支持用户自有的 `.local/bin`、`.local/opt`、XDG 数据目录和 `~/Applications`。先解析程序和简单包装脚本，再列出专用目录、桌面入口、独占图标、自启动和匹配的用户服务；确认后关闭目标程序并删除清单内文件。保留外部配置和共享图标。无法确认归属的系统目录、跨用户路径和目录符号链接不递归删除。
- APT 会展示删除及替代安装计划，执行前再次核对。核心包管理、权限和运行依赖受到保护；涉及桌面、登录或网络组件时，需输入应用名称确认。
- APT 不使用 purge/autoremove，Snap 不使用 `--purge`，Flatpak 不使用 `--delete-data`。应用维护脚本仍可能改变数据；专用安装目录内的个人文件应提前备份。
- 操作锁冲突、授权取消或命令超时会报告失败。其他包管理进程可能改变系统状态；重试前应先确认软件管理状态。
- 卸载记录保存在 `$XDG_STATE_HOME/miemie-app-manager/history.json`，默认 `~/.local/state/miemie-app-manager/history.json`，最多保留 200 条。

## 开发与验证

```bash
/usr/bin/python3 -m unittest discover -s tests -v
GDK_BACKEND=x11 /usr/bin/python3 scripts/preview.py .local/preview
/usr/bin/python3 scripts/build-deb.py
```

`preview.py` 仅使用示例数据生成原生界面截图并验证排序，不扫描或卸载实际应用。`smoke.py` 读取实际安装应用，验证搜索、筛选、卸载计划与确认取消；不实际卸载。完整说明见 [验证记录](docs/VERIFICATION.md) 和 [更新记录](CHANGELOG.md)。

系统操作语义参考 [Ubuntu APT 手册](https://manpages.ubuntu.com/manpages/resolute/man8/apt-get.8.html) 和 [Ubuntu 软件管理说明](https://wiki.ubuntu.com/Managing_software_on_Ubuntu)。

## 许可证

[MIT](LICENSE)。
