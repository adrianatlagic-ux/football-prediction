#!/usr/bin/env python3
"""Render code-drawn German titles/stats over locally available video assets."""
import argparse
import json
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw, ImageFont

W, H = 720, 1280
GOLD = '#d4af37'
FONT = '/System/Library/Fonts/Supplemental/Arial Bold.ttf'


def run(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def wrapped(draw, text, size, width=600):
    font = ImageFont.truetype(FONT, size)
    lines = []
    for paragraph in text.split('\n'):
        line = ''
        for word in paragraph.split():
            candidate = (line + ' ' + word).strip()
            if draw.textlength(candidate, font=font) > width and line:
                lines.append(line); line = word
            else:
                line = candidate
        lines.append(line)
    return font, lines


def text_block(draw, text, y, size=40, color='white', max_lines=3):
    for fitted in range(size, 13, -1):
        font, lines = wrapped(draw, text, fitted)
        if len(lines) <= max_lines and all(draw.textlength(line, font=font) <= 600 for line in lines):
            break
    else:
        raise ValueError('Text too long; shorten the scene copy')
    for line in lines:
        draw.text((W/2, y), line, font=font, fill=color, anchor='mt')
        y += fitted + 10
    return y


def render(manifest):
    data = json.loads(manifest.read_text())
    folder = manifest.parent
    scenes = data['scenes']
    if not scenes or not 12 <= sum(s['duration'] for s in scenes) <= 30:
        raise ValueError('Need 12–30 seconds of scenes')
    names_path = Path(__file__).resolve().parents[2] / 'frontend/src/team_names_de.json'
    names = json.loads(names_path.read_text()) if names_path.exists() else {}
    names.update({'Spain':'Spanien','England':'England','Croatia':'Kroatien','Czech Republic':'Tschechien',
                  'Switzerland':'Schweiz','Scotland':'Schottland','Finland':'Finnland','Albania':'Albanien',
                  'Greece':'Griechenland','Germany':'Deutschland','Norway':'Norwegen','Portugal':'Portugal'})
    segments = []
    for index, scene in enumerate(scenes):
        duration = float(scene['duration'])
        if not 2 <= duration <= 12: raise ValueError('scene duration must be 2–12 seconds')
        art = Image.new('RGBA', (W,H), (0,0,0,0))
        draw = ImageDraw.Draw(art)
        draw.rectangle((0,0,W,300), fill=(5,5,5,220))
        draw.rectangle((0,900,W,H), fill=(5,5,5,232))
        text_block(draw, 'GOALFIQ', 62, 28, GOLD)
        text_block(draw, scene['headline'], 120, 46)
        if 'match_index' in scene:
            match = data['selected'][scene['match_index']]
            title = names.get(match['home_team'],match['home_team'])+' – '+names.get(match['away_team'],match['away_team'])
            text_block(draw, title, 915, 30, GOLD, 2)
            p = match['probabilities']
            percentage = lambda n: f'{100*n:.1f}'.replace('.', ',')+' %'
            text_block(draw, f"1: {percentage(p['home'])}   X: {percentage(p['draw'])}   2: {percentage(p['away'])}", 1015, 27)
            text_block(draw, 'Modellprognose · '+match['date']+' · '+match['time'], 1060, 20)
        else:
            text_block(draw, scene.get('body','Dein Spiel. Deine Prognose.'), 955, 33, max_lines=3)
        text_block(draw, 'goalfiq.de', 1140, 26, GOLD)
        text_block(draw, 'KI-Inszenierung · keine echten Spielszenen', 1180, 17)
        overlay = folder / f'overlay-{index:02}.png'; art.save(overlay)
        dest = folder / f'segment-{index:02}.mp4'
        args = ['ffmpeg','-y','-loglevel','error']
        source = scene.get('asset')
        if source:
            asset = (folder / source).resolve()
            if not asset.is_file(): raise ValueError('Missing asset: '+str(asset))
            if asset.suffix.lower() in ('.png','.jpg','.jpeg','.webp'):
                args += ['-loop','1','-i',str(asset)]
            else:
                args += ['-stream_loop','-1','-i',str(asset)]
        else:
            args += ['-f','lavfi','-i',f'color=c=0x050505:s={W}x{H}:r=30']
        args += ['-loop','1','-i',str(overlay),'-filter_complex',
                 f'[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps=30[bg];[bg][1:v]overlay=0:0:shortest=1[v]',
                 '-map','[v]','-an','-t',str(duration),'-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',str(dest)]
        run(args); segments.append(dest)
    concat = folder / 'segments.txt'
    concat.write_text(''.join(f"file '{p.name}'\n" for p in segments))
    output = folder / 'final.mp4'
    args = ['ffmpeg','-y','-loglevel','error','-f','concat','-safe','0','-i',str(concat)]
    audio = data.get('audio_asset')
    if audio:
        asset = (folder/audio).resolve()
        if not asset.is_file(): raise ValueError('missing audio asset')
        args += ['-stream_loop','-1','-i',str(asset),'-map','0:v:0','-map','1:a:0',
                 '-af','loudnorm=I=-16:TP=-1.5:LRA=11','-c:a','aac','-b:a','160k']
    else:
        args += ['-an']
    args += ['-c:v','copy','-t',str(sum(s['duration'] for s in scenes)),'-movflags','+faststart',str(output)]
    run(args)
    (folder/'caption.txt').write_text(data.get('caption',''))
    print(output)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('manifest', type=Path)
    render(p.parse_args().manifest.resolve())
