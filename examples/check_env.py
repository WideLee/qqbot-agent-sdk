#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环境检查脚本

在运行 E2E 测试前检查环境是否正确配置。
"""

import sys


def check_python_version():
    """检查 Python 版本"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 10):
        print("❌ Python 版本过低，需要 Python 3.10+")
        print(f"   当前版本: {version.major}.{version.minor}.{version.micro}")
        return False
    print(f"✓ Python 版本: {version.major}.{version.minor}.{version.micro}")
    return True


def check_module(module_name, package_name=None, optional=False):
    """检查模块是否已安装"""
    try:
        __import__(module_name)
        print(f"✓ {package_name or module_name}")
        return True
    except ImportError:
        if optional:
            print(f"⚠ {package_name or module_name} (可选)")
        else:
            print(f"❌ {package_name or module_name} 未安装")
        return not optional


def main():
    """主函数"""
    print("=" * 60)
    print("QQBot SDK E2E 测试环境检查")
    print("=" * 60)
    print()
    
    all_ok = True
    
    # 检查 Python 版本
    print("1. Python 版本")
    all_ok &= check_python_version()
    print()
    
    # 检查必需依赖
    print("2. 必需依赖")
    all_ok &= check_module("httpx")
    all_ok &= check_module("aiohttp")
    all_ok &= check_module("cryptography")
    all_ok &= check_module("qqbot_agent_sdk", "qqbot-agent-sdk")
    print()
    
    # 检查可选依赖
    print("3. 可选依赖（推荐安装）")
    has_qrcode = check_module("qrcode", optional=True)
    has_pil = check_module("PIL", "Pillow (用于 qrcode)", optional=True)
    if not (has_qrcode and has_pil):
        print("   💡 提示: 安装后可在终端直接显示二维码")
        print("   安装命令: pip install qrcode[pil]")
    print()
    
    # 检查测试文件
    print("4. 测试文件")
    from pathlib import Path
    test_dir = Path(__file__).parent / "e2e_test_files"
    if test_dir.exists():
        print(f"✓ 测试目录: {test_dir}")
        files = ["test.txt", "test.png"]
        for f in files:
            if (test_dir / f).exists():
                print(f"  ✓ {f}")
            else:
                print(f"  ⚠ {f} (将在运行时创建)")
    else:
        print(f"⚠ 测试目录不存在，将在运行时创建")
    print()
    
    # 总结
    print("=" * 60)
    if all_ok:
        print("✅ 环境检查通过！可以运行 E2E 测试")
        print()
        print("运行测试:")
        print("  python examples/e2e_test.py")
    else:
        print("❌ 环境检查失败，请先安装缺失的依赖")
        print()
        print("安装依赖:")
        print("  pip install qqbot-agent-sdk")
        print("  pip install qrcode[pil]  # 可选，用于显示二维码")
    print("=" * 60)
    
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
