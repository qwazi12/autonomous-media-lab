#!/usr/bin/env python3
"""Original illustrated production fixtures. Not movie/anime clips or model quality benchmarks."""
import json,subprocess,sys
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from pipeline import ff,save
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
def font(n):return ImageFont.truetype(FONT,n)
SAMPLES={
'movie':('THE LAST SIGNAL',[("A light in the storm",'Mara repairs a lighthouse after a storm cuts the island off. She discovers that the beacon can still send one brief signal before its battery fails.'),("The choice",'A fishing boat appears beyond the reef. Mara must choose between saving the remaining power for herself and warning the approaching crew.'),("A safe passage",'She uses the final charge to illuminate the rocks. The boat turns toward a safer channel, and Mara watches its lights disappear into the dawn.')]),
'tv':('HARBOR FILES · EPISODE 1',[("A missing map",'In this original episode, investigator June arrives at the harbor to find a navigation map missing. A clerk recalls someone leaving the office before sunrise.'),("One useful clue",'June notices that the office window is open, but the desk is dry despite the rain. She decides to question the clerk about the timing rather than assume a break-in.'),("An unfinished case",'The clerk admits moving the map into storage to protect it. When June opens the cabinet, the map is there, but one marked page is missing. The episode ends with that question unresolved.')]),
'anime':('THE GLASS GARDEN',[("A fragile world",'In this original animated-story fixture, apprentice Ren tends a garden of glass flowers. Each morning, the garden captures a little sunlight and releases it after dark.'),("A broken flower",'Ren accidentally breaks the tallest flower. Instead of hiding the damage, Ren gathers the fragments and asks the gardener whether they can be used again.'),("A different design",'Together they arrange the fragments into a low mosaic. It cannot replace the tall flower, but it casts a new pattern of light across the path.')]),
'manhwa':('THE CLOCKMAKER’S APPRENTICE',[("Panel one · arrival",'The apprentice arrives at a silent workshop carrying a damaged clock. The clockmaker points to an empty bench, inviting the apprentice to begin.'),("Panel two · discovery",'Inside the clock, the apprentice finds a small gear trapped beneath the spring. Removing it frees the mechanism, but reveals that one tooth is missing.'),("Panel three · repair",'The apprentice shapes a replacement gear and tests the clock. The hands begin moving again. The clockmaker nods, and the repaired clock returns to its owner.')]),
'educational':('WHY SHADOWS CHANGE',[("Light travels outward",'A shadow forms when an object blocks light from reaching a surface. In this simplified diagram, a lamp shines toward a wall, and a solid object interrupts some of those rays.'),("Move the object",'With the lamp and wall fixed, moving the object closer to the lamp makes its shadow larger. The object blocks a wider bundle of rays before they reach the wall.'),("Check the model",'This explanation assumes a small light source and a flat wall. A large light source also creates a softer edge, called the penumbra. You can compare the two effects with a flashlight and a piece of card.')])}
def draw_card(path,title,label,i,kind):
    im=Image.new('RGB',(1280,720),'#101827');d=ImageDraw.Draw(im)
    d.rectangle((0,0,1280,8),fill='#5ce0bd');d.text((60,38),title,font=font(35),fill='white')
    d.text((60,92),'ORIGINAL SYNTHETIC STORYBOARD · PIPELINE SAMPLE',font=font(17),fill='#93adc7')
    d.rounded_rectangle((60,140,1220,610),radius=24,fill=['#18324d','#253753','#183b47'][i])
    if kind=='educational':
        x=310-i*45;d.ellipse((160,310,210,360),fill='#ffe28a');d.rectangle((1030,210,1050,530),fill='#d8e5f0')
        d.polygon([(185,335),(1040,180-i*40),(1040,550+i*10)],fill='#365771')
        d.line((185,335,1040,180-i*40),fill='#ffe28a',width=4);d.line((185,335,1040,550+i*10),fill='#ffe28a',width=4)
        d.rectangle((x,290,x+25,390),fill='#f29f80');d.text((150,430),'Lamp',font=font(22),fill='white');d.text((1000,560),'Wall',font=font(22),fill='white')
    else:
        d.rectangle((80,470,1200,590),fill='#101e31')
        for x in range(100,1200,120):d.rectangle((x,380-(x%70),x+75,470),fill='#294563')
        # Distinct abstract story motifs, not copied art.
        if kind=='movie':
            d.polygon([(300,460),(335,230),(405,230),(440,460)],fill='#d7e7ed');d.rectangle((320,210,420,255),fill='#f8d784');d.polygon([(420,230),(1060,160),(1060,320)],fill='#476477')
        elif kind=='tv':
            d.rounded_rectangle((270,220,640,430),radius=8,fill='#e4cf9c');d.line((300,390,390,260,500,360,600,250),fill='#946c53',width=7);d.ellipse((510,280,640,410),outline='#a9d9ee',width=12)
        elif kind=='anime':
            for x in [320,460,610,760]:
                d.line((x,470,x,320-i*25),fill='#6ee4ba',width=8);d.polygon([(x,245),(x-45,315),(x,365),(x+45,315)],fill='#aad9ef')
        else:
            d.ellipse((280,220,580,500),fill='#d6bd85',outline='#efdfb7',width=12);d.line((430,360,430,265),fill='#153248',width=8);d.line((430,360,510,400),fill='#153248',width=8)
        d.ellipse((900,265,975,340),fill='#f0bc9c');d.rounded_rectangle((890,340,985,475),radius=20,fill='#70c7b1');d.line((910,475,895,545),fill='#70c7b1',width=15);d.line((965,475,980,545),fill='#70c7b1',width=15)
    d.text((60,645),label,font=font(30),fill='white');d.text((1150,650),f'{i+1}/3',font=font(24),fill='#5ce0bd');im.save(path)
def main():
    root=Path(sys.argv[1] if len(sys.argv)>1 else 'samples').resolve();root.mkdir(exist_ok=False,parents=True)
    for kind,(title,beats) in SAMPLES.items():
        base=root/kind;base.mkdir();panels=[]
        for i,(label,text) in enumerate(beats):
            draw_card(base/f'{i}.png',title,label,i,kind)
            panels.append({'image':f'{i}.png','description':label,'evidence':[text],'source_url':'urn:original:sample-script','as_of':'2026-11-09'})
            ff(['-loop','1','-i',str(base/f'{i}.png'),'-t','30','-vf','scale=1280:720','-r','24','-pix_fmt','yuv420p','-c:v','libx264',str(base/f'{i}.mp4')])
        (base/'concat.txt').write_text(''.join(f"file '{i}.mp4'\n" for i in range(3)))
        ff(['-f','concat','-safe','1','-i',str(base/'concat.txt'),'-c','copy',str(base/'source.mp4')])
        save(base/'manifest.json',{'cards' if kind=='educational' else 'panels':panels})
        save(base/'plan.json',{'title':title+' — synthetic prototype sample','segments':[{'id':f'B{i+1:03}','narration':text,'scene_ids':[f'S{i+1:05}'],'review_notes':['Original hand-authored script fixture; not a generated movie summary.']} for i,(_,text) in enumerate(beats)]})
        source=base/'manifest.json' if kind in ('manhwa','educational') else base/'source.mp4'
        subprocess.run([sys.executable,str(Path(__file__).with_name('pipeline.py')),'--source',str(source),'--output',str(base/'run'),'--plan',str(base/'plan.json'),'--workflow',kind,'--rights-confirmed'],check=True)
if __name__=='__main__':main()
