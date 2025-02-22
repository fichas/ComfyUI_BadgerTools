import os
import subprocess
import shutil
import open_clip
import cv2
from sentence_transformers import util
from PIL import Image
from skimage import metrics
from moviepy import VideoFileClip
import comfy.model_management as model_management

def SSIM(imgPath0, imgPath1):
    image1 = cv2.imread(imgPath0)
    image2 = cv2.imread(imgPath1)
    image2 = cv2.resize(image2, (image1.shape[1], image1.shape[0]), interpolation=cv2.INTER_AREA)
    # Convert images to grayscale
    image1_gray = cv2.cvtColor(image1, cv2.COLOR_BGR2GRAY)
    image2_gray = cv2.cvtColor(image2, cv2.COLOR_BGR2GRAY)
    # Calculate SSIM
    ssim_score = metrics.structural_similarity(image1_gray, image2_gray, full=True)
    return round(ssim_score[0], 2) * 100


def imageEncoder(model,preprocess,device,img):
    if img.dtype == 'uint16': 
        img = (img / 256).astype('uint8')
    if img.shape[2] == 4:  
        img = img[:, :, :3] 
    img1 = Image.fromarray(img).convert('RGB')
    img1 = preprocess(img1).unsqueeze(0).to(device)
    img1 = model.encode_image(img1)
    return img1


def generateScore(model,preprocess,device,image1, image2):
    test_img = cv2.imread(image1, cv2.IMREAD_UNCHANGED)
    data_img = cv2.imread(image2, cv2.IMREAD_UNCHANGED)
    img1 = imageEncoder(model,preprocess,device,test_img)
    img2 = imageEncoder(model,preprocess,device,data_img)
    cos_scores = util.pytorch_cos_sim(img1, img2)
    score = round(float(cos_scores[0][0]) * 100, 2)
    return score


def getCutList(imagepath, min_frame, max_frame):
    device = model_management.get_torch_device()
    model, _, preprocess = open_clip.create_model_and_transforms('ViT-B-16-plus-240', pretrained="laion400m_e32",
                                                                 cache_dir="./models/clip")
    model.to(device)
    pngList = sorted(os.listdir(imagepath))
    cutList = []
    resList = []
    indexList = []
    i = min_frame - 1
    num = min_frame - 1
    while i < len(pngList) - 1:
        num += 1
        imgPath0 = os.path.join(imagepath, pngList[i])
        imgPath1 = os.path.join(imagepath, pngList[i + 1])
        res = generateScore(model,preprocess,device,imgPath0, imgPath1)
        print("切割画面（" + str(i + 1) + "/" + str(len(pngList) - 1) + ")" + str(res))
        resList.append(res)
        indexList.append(i)
        if num >= max_frame:
            num = min_frame - 1
            cutList.append(pngList[i])
            i += min_frame
        elif res < 95:
            res2 = SSIM(imgPath0, imgPath1)
            if res2 < 60:
                res3 = (95 - res) ** 2 + (60 - res2) ** 2
                print(res3)
                if (res3 > 150):
                    num = min_frame - 1
                    cutList.append(pngList[i])
                    i += min_frame
                else:
                    i += 1
            else:
                i += 1
        else:
            i += 1
    del model
    print(cutList)
    return cutList


def video_to_frames(video_path, min_side_length, frame_rate, save_name):
    current_file_path = __file__
    absolute_path = os.path.abspath(current_file_path)
    directory = os.path.dirname(absolute_path)

    all_cut_dir = os.path.join(directory, "VideoCutDir")

    video = VideoFileClip(video_path)
    width, height = video.size

    if height < width:
        width = -1
        height = min_side_length
    else:
        width = min_side_length
        height = -1

    if not os.path.exists(all_cut_dir):
        os.mkdir(all_cut_dir)
    root_dir = os.path.join(all_cut_dir, save_name)
    if os.path.exists(root_dir):
        shutil.rmtree(root_dir)
    os.mkdir(root_dir)
    size = str(width) + ":" + str(height)
    ffmpegCMD = [
        'ffmpeg',
        '-i', video_path,  # 输入视频路径
        '-vf', f'fps={frame_rate},scale={size}',  # 设置帧率和缩放
        '-q:v', '2',  # 设置输出质量
        os.path.join(root_dir, 'frame_%05d.png')  # 输出文件名和格式
    ]
    subprocess.run(ffmpegCMD, check=True)
    print("视频转图片完成")

    return root_dir


def frames_to_video(input_folder, frame_rate, output_path):
    # Get a sorted list of (non-hidden) image files
    files = [f for f in sorted(os.listdir(input_folder)) if not f.startswith('.')]
    sorted_files = sorted(files, key=lambda x: os.path.splitext(x)[0])

    # Create a temporary file listing all images for ffmpeg
    temp_list_path = 'ffmpeg_temp_list.txt'
    with open(temp_list_path, 'w') as filelist:
        for filename in sorted_files[:-1]:
            file_path = os.path.join(input_folder, filename)
            filelist.write(f"file '{file_path}'\n")
            filelist.write(f"duration {1 / frame_rate}\n")
        # Write the last file without a duration
        filelist.write(f"file '{os.path.join(input_folder, sorted_files[-1])}'\n")

    # Construct the ffmpeg command to create the video
    command = [
        'ffmpeg',
        '-f', 'concat',  # Use the concat demuxer
        '-safe', '0',  # Allow unsafe file paths
        '-i', temp_list_path,  # Input file list
        '-vsync', 'vfr',  # Variable frame rate mode to match input sequence
        '-pix_fmt', 'yuv420p',  # Pixel format, widely compatible
        '-c:v', 'libx264',  # Codec to use for encoding
        '-crf', '23',  # Constant Rate Factor, controls quality (lower is better)
        output_path
    ]

    # Execute the command
    try:
        subprocess.run(command, check=True)
        print(f'Video has been created at {output_path}')
    except subprocess.CalledProcessError as e:
        print(f'An error occurred: {e}')
    finally:
        # Clean up temporary file
        if os.path.exists(temp_list_path):
            os.remove(temp_list_path)


def cutToDir(root_dir, cutList):
    dirIndex = 0
    pngList = sorted(os.listdir(root_dir))
    dirList = []
    dirPathList = []
    for i in range(len(cutList) + 1):
        dirName = str(i).zfill(3)
        dirPath = os.path.join(root_dir, dirName)
        os.mkdir(dirPath)
        dirPathList.append(dirPath)
        dirList.append(dirName)
    for png in pngList:
        src = os.path.join(root_dir, png)
        tgtDir = os.path.join(root_dir, dirList[dirIndex])
        shutil.move(src, tgtDir)
        if png in cutList:
            dirIndex += 1

    return "\n".join(dirPathList)
