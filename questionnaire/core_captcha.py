# questionnaire/core_captcha.py
import random
import string
import time
import numpy as np
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
import math
from scipy import interpolate

def generate_captcha_text(length=4):
    """生成验证码文本 - 混合大小写字母和数字，排除易混淆字符"""
    # 移除易混淆字符：0, O, o, 1, I, l, L,Z,2,7,S,R
    letters = 'abcdefghjkmnpqtuvwxyzABCDEFGHJKMNPQRSTUVWXY345689'
    # 确保至少有一个数字
    text = ''.join(random.choices(letters, k=length - 1))
    text += random.choice('23456789')
    # 打乱顺序
    text_list = list(text)
    random.shuffle(text_list)
    return ''.join(text_list)


def add_noise(image):
    """添加干扰元素"""
    draw = ImageDraw.Draw(image)
    width, height = image.size

    # 添加随机噪点
    for _ in range(100):
        x = random.randint(0, width)
        y = random.randint(0, height)
        draw.point((x, y), fill=random.choice(['gray', 'lightgray', 'darkgray']))

    # 添加随机干扰线
    for _ in range(5):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        color = random.choice(['gray', 'lightblue', 'lightgreen', 'pink'])
        draw.line([(x1, y1), (x2, y2)], fill=color, width=1)

    # 添加随机干扰弧线
    for _ in range(3):
        x1 = random.randint(0, width // 2)
        y1 = random.randint(0, height // 2)
        x2 = random.randint(width // 2, width)
        y2 = random.randint(height // 2, height)
        start = random.randint(0, 360)
        end = random.randint(0, 360)
        color = random.choice(['lightgray', 'silver'])
        draw.arc([x1, y1, x2, y2], start, end, fill=color, width=1)

    return image


def warp_image(image):
    """扭曲图像，增加识别难度"""
    width, height = image.size

    # 创建扭曲网格
    magnitude = random.uniform(1.5, 3.0)
    grid_size = 8

    import numpy as np
    # 创建扭曲效果
    xp = np.linspace(0, width, grid_size)
    yp = np.linspace(0, height, grid_size)
    xp, yp = np.meshgrid(xp, yp)

    # 添加随机扰动
    xp += np.random.randn(grid_size, grid_size) * magnitude
    yp += np.random.randn(grid_size, grid_size) * magnitude

    # 转换为PIL可用的格式
    from PIL import Image
    import numpy as np

    # 转换为numpy数组进行处理
    img_array = np.array(image)

    # 简单的扭曲效果 - 正弦波扭曲
    rows, cols = height, width
    src_cols = np.linspace(0, cols, 20)
    src_rows = np.linspace(0, rows, 20)
    src_rows, src_cols = np.meshgrid(src_rows, src_cols)

    # 应用正弦波扭曲
    amplitude = random.uniform(2, 5)
    frequency = random.uniform(0.05, 0.1)
    dst_rows = src_rows + amplitude * np.sin(2 * np.pi * frequency * src_cols)
    dst_cols = src_cols + amplitude * np.cos(2 * np.pi * frequency * src_rows)

    # 重新采样图像
    try:
        from scipy.interpolate import griddata
        # 创建网格点
        points = np.array([src_rows.ravel(), src_cols.ravel()]).T
        values_r = img_array[:, :, 0].ravel()
        values_g = img_array[:, :, 1].ravel()
        values_b = img_array[:, :, 2].ravel()

        # 创建目标网格
        grid_x, grid_y = np.mgrid[0:rows:1, 0:cols:1]

        # 插值
        grid_r = griddata(points, values_r, (grid_x, grid_y), method='linear')
        grid_g = griddata(points, values_g, (grid_x, grid_y), method='linear')
        grid_b = griddata(points, values_b, (grid_x, grid_y), method='linear')

        # 合并通道
        warped = np.stack([grid_r, grid_g, grid_b], axis=2)
        warped = np.clip(warped, 0, 255).astype(np.uint8)

        return Image.fromarray(warped)
    except ImportError:
        # 如果没有scipy，使用简单方法
        return image.filter(ImageFilter.SMOOTH_MORE)


def create_captcha_image(text):
    """创建更复杂的验证码图片"""
    width, height = 200, 90  # 稍微加大尺寸
    image = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(image)

    # 尝试加载不同字体
    fonts = []
    font_sizes = [40, 44, 48]

    # 尝试不同字体
    font_paths = [
        #None,  # 默认字体（最后备用，但很小，仅作兜底）
        "arial.ttf",  # Windows
        "arialbd.ttf",
        "times.ttf",
        "cour.ttf",
        "DejaVuSans.ttf",  # Linux 常见字体名
        "LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Debian/Ubuntu
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/abattis/cantarell/Cantarell-Regular.ttf",  # Fedora
        "C:/Windows/Fonts/Arial.ttf"  # Windows 绝对路径（Linux 无效，但无影响）
    ]

    for font_path in font_paths:
        for font_size in font_sizes:
            try:
                if font_path:
                    font = ImageFont.truetype(font_path, font_size)
                else:
                    # 使用默认字体
                    font = ImageFont.load_default()
                fonts.append(font)
            except Exception as e:
                # 如果字体加载失败，跳过这个字体
                continue

    # 如果没有成功加载任何字体，使用默认字体
    if not fonts:
        try:
            font = ImageFont.load_default()
            fonts = [font]
        except:
            # 如果默认字体也失败，使用一个简单的字体替代
            from PIL import ImageFont as IF
            font = IF.load_default()
            fonts = [font]

    # 绘制文本 - 每个字符使用不同的字体、颜色和旋转
    char_width = width // len(text)
    for i, char in enumerate(text):
        # 随机选择字体
        font = random.choice(fonts)

        # 随机颜色（避免太浅）
        colors = ['darkred', 'navy', 'darkgreen', 'purple', 'maroon', 'teal']
        color = random.choice(colors)

        # 随机位置（轻微偏移）
        x = i * char_width + random.randint(2, 10)
        y = random.randint(5, 15)

        # 创建字符图像层
        char_image = Image.new('RGBA', (char_width, height), (255, 255, 255, 0))
        char_draw = ImageDraw.Draw(char_image)

        # 随机旋转
        rotation = random.randint(-20, 20)

        # 绘制字符
        char_draw.text((10, y), char, fill=color, font=font)

        # 应用旋转
        if rotation != 0:
            char_image = char_image.rotate(rotation, expand=1, fillcolor=(255, 255, 255, 0))

        # 合并到主图像
        char_x = max(0, min(x, width - char_image.width))
        char_y = max(0, min(0, height - char_image.height))
        image.paste(char_image, (char_x, char_y), char_image)

    # 添加干扰元素
    image = add_noise(image)

    # 应用模糊效果
    image = image.filter(ImageFilter.SMOOTH)

    # 添加边框
    draw.rectangle([0, 0, width - 1, height - 1], outline='gray', width=1)

    # 保存到内存
    buffer = BytesIO()
    image.save(buffer, format='PNG', quality=85)
    return buffer.getvalue()

def generate_and_store_captcha(request):
    """生成验证码并存储到session，返回图片响应"""
    # 生成验证码文本
    captcha_text = generate_captcha_text()

    # 存储到session（同时存储文本和生成时间）
    request.session['captcha_text'] = captcha_text
    request.session['captcha_time'] = time.time()

    # 生成图片
    image_data = create_captcha_image(captcha_text)

    # 返回图片响应
    response = HttpResponse(image_data, content_type='image/png')
    # 设置不缓存头
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'

    return response


def verify_captcha(request, user_input):
    """验证用户输入的验证码"""
    if not user_input:
        return False, '验证码不能为空'

    # 从session获取存储的验证码
    stored_text = request.session.get('captcha_text')
    stored_time = request.session.get('captcha_time')

    if not stored_text or not stored_time:
        return False, '验证码已过期，请刷新重试'

    # 检查是否过期（5分钟）
    if time.time() - stored_time > 300:  # 300秒 = 5分钟
        # 清除过期的验证码
        clear_captcha(request)
        return False, '验证码已过期，请刷新重试'

    # 比较验证码（不区分大小写）
    if str(user_input).strip().lower() != str(stored_text).lower():
        # 验证失败后立即清除，防止重试
        clear_captcha(request)
        return False, '验证码错误'

    # 验证成功，清除验证码（一次性使用）
    clear_captcha(request)
    return True, '验证通过'


def clear_captcha(request):
    """清除session中的验证码"""
    if 'captcha_text' in request.session:
        del request.session['captcha_text']
    if 'captcha_time' in request.session:
        del request.session['captcha_time']


def refresh_captcha_ajax(request):
    """AJAX刷新验证码（返回新的图片URL）"""
    # 生成新的验证码
    captcha_text = generate_captcha_text()
    request.session['captcha_text'] = captcha_text
    request.session['captcha_time'] = time.time()

    # 返回JSON响应
    return JsonResponse({
        'success': True,
        'new_url': f'/captcha/image/?t={int(time.time() * 1000)}'
    })