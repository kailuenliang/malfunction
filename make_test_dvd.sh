#!/usr/bin/env bash
# Build a fake, unencrypted DVD title set (TESTDISC/VIDEO_TS/VTS_01_1.VOB)
# from ffmpeg test patterns, with hard cuts between four "shots".
set -e
mkdir -p TESTDISC/VIDEO_TS
ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "testsrc2=s=720x480:r=30000/1001:d=4" \
  -f lavfi -i "mandelbrot=s=720x480:r=30000/1001" \
  -f lavfi -i "life=s=720x480:r=30000/1001:mold=10:ratio=0.1:death_color=#C83232:life_color=#00ff00" \
  -f lavfi -i "smptehdbars=s=720x480:r=30000/1001:d=4" \
  -f lavfi -i "sine=f=220:d=16" \
  -filter_complex "[1]trim=duration=4,setpts=PTS-STARTPTS[m];[2]trim=duration=4,setpts=PTS-STARTPTS,format=yuv420p[l];[3]rotate=a=t*0.5,format=yuv420p[s];[0][m][l][s]concat=n=4:v=1:a=0[v]" \
  -map "[v]" -map 4:a -target ntsc-dvd -aspect 16:9 TESTDISC/VIDEO_TS/VTS_01_1.VOB
echo "built TESTDISC/VIDEO_TS/VTS_01_1.VOB"
