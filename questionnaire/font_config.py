import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import os


def init_matplotlib_font():
    """加载项目中的字体文件，确保 matplotlib 中文正常显示"""
    # 获取当前文件所在目录的上级目录的上级目录（即项目根目录）
    base_dir = os.path.dirname(os.path.dirname(__file__))
    font_path = os.path.join(base_dir, 'static', 'fonts', 'simhei.ttf')

    if os.path.exists(font_path):
        # 添加字体文件到 matplotlib 字体管理器
        fm.fontManager.addfont(font_path)
        font_name = fm.FontProperties(fname=font_path).get_name()
        # 设置为默认 sans-serif 字体
        plt.rcParams['font.sans-serif'] = [font_name] + plt.rcParams.get('font.sans-serif', [])
        print(f"✅ 成功加载字体: {font_name} 从 {font_path}")
    else:
        print(f"⚠️ 字体文件不存在: {font_path}，尝试使用系统字体")
        # 回退到常见字体
        fallback_fonts = ['SimHei', 'Microsoft YaHei', 'WenQuanYi Micro Hei']
        for font in fallback_fonts:
            try:
                fm.findfont(font, fallback_to_default=False)
                plt.rcParams['font.sans-serif'] = [font]
                print(f"✅ 使用系统字体: {font}")
                break
            except:
                continue
    plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题