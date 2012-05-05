#! /usr/bin/env python2

# GNU Waterfall
# licensed GPLv3

import sys, math, time, numpy, pyglet, rtlsdr
from pyglet.gl import *
from pyglet.window import key
from itertools import *

from radio_math import psd

if len(sys.argv) != 3:
    print "use: gnuwaterfall.py <start> <stop>"
    print "    frequencies in hertz"
    print "    example: gnuwaterfall.py 80e6 100e6"
    print "    arrow keys pan and zoom"
    print "    esc to quit"
    sys.exit(2)

freq_lower = float(sys.argv[1])
freq_upper = float(sys.argv[2])
time_start = time.time()
viewport = (0,0,1,1)
history = 60  # seconds

# Since this is dealing with a stupid amount of data in the video ram,
# the x axis is MHz and the y axis is seconds.
# Nothing is ever updated to scroll, instead panning moves the viewport
# and changes the aspect ratio.
# Good luck drawing widgets on top of that.
# (See the text() function for the required contortions to overlay.)

class SdrWrap(object):
    "wrap sdr and try to manage tuning"
    def __init__(self):
        self.sdr = rtlsdr.RtlSdr()
        self.read_samples = self.sdr.read_samples
        self.prev_fc = None
        self.prev_fs = None
        self.sdr.gain = 1
    def tune(self, fc, fs):
        if fc == self.prev_fc and fs == self.prev_fs:
            return
        if fc != self.prev_fc:
            self.sdr.center_freq = fc
        if fs != self.prev_fs:
            self.sdr.sample_rate = fs
        self.prev_fc = fc
        self.prev_fs = fs
        time.sleep(0.04)  # wait for settle
        self.sdr.read_samples(2**11)  # clear buffer

sdr = SdrWrap()

try:
    config = pyglet.gl.Config(sample_buffers=1, samples=4, double_buffer=True)
    window = pyglet.window.Window(config=config, resizable=True)
except pyglet.window.NoSuchConfigException:
    print 'Disabling 4xAA'
    window = pyglet.window.Window(resizable=True)
window.clear()
glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
glEnable(GL_BLEND)
glEnable(GL_LINE_SMOOTH)
glHint(GL_LINE_SMOOTH_HINT, GL_DONT_CARE)

@window.event
def on_draw():
    pass

@window.event
def on_key_press(symbol, modifiers):
    global freq_lower, freq_upper
    delta = freq_upper - freq_lower
    if   symbol == key.LEFT:
        freq_lower -= delta * 0.1
        freq_upper -= delta * 0.1
    elif symbol == key.RIGHT:
        freq_lower += delta * 0.1
        freq_upper += delta * 0.1
    elif symbol == key.UP:
        freq_lower += delta * 0.1
        freq_upper -= delta * 0.1
    elif symbol == key.DOWN:
        freq_lower -= delta * 0.1
        freq_upper += delta * 0.1
    freq_lower = max(60e6, freq_lower)
    freq_upper = min(1700e6, freq_upper)
    #print '%0.2fMHz - %0.2fMHz' % (freq_lower/1e6, freq_upper/1e6)


vertexes = {}  # timestamp : vertex_list
batch = pyglet.graphics.Batch()

def mapping(x):
    "assumes -50 to 0 range, returns color"
    r = int((x+50) * 255 // 50)
    r = max(0, r)
    r = min(255, r)
    return r,r,100

def log2(x):
    return math.log(x)/math.log(2)

def acquire_sample(center, bw, detail, samples=8):
    "collect a single frequency"
    assert bw <= 2.8e6
    if detail < 8:
        detail = 8
    sdr.tune(center, bw)
    detail = 2**int(math.ceil(log2(detail)))
    sample_count = samples * detail
    data = sdr.read_samples(sample_count)
    ys,xs = psd(data, NFFT=detail, Fs=bw/1e6, Fc=center/1e6)
    ys = 10 * numpy.log10(ys)
    return xs, ys

def acquire_range(lower, upper):
    "collect multiple frequencies"
    if upper - lower < 2.8e6:
        # single sample
        return acquire_sample((upper+lower)/2, upper-lower, detail=window.width)
    xs2 = numpy.array([])
    ys2 = numpy.array([])
    detail = window.width // ((upper-lower)/(2.8e6))
    for f in range(int(lower), int(upper), int(2.8e6)):
        xs,ys = acquire_sample(f+1.4e6, 2.8e6, detail=detail)
        xs2 = numpy.append(xs2, xs) 
        ys2 = numpy.append(ys2, ys) 
    return xs2, ys2

def render_sample(now, dt, freqs, powers):
    global vertexes
    min_p = min(powers)
    max_p = max(powers)
    quads = []
    colors = []
    for i,f in enumerate(freqs):
        quads.extend([f, now, f, now-dt])
        rgb = mapping(powers[i])
        colors.extend(rgb)
        colors.extend(rgb)
    # not using batches for now, it bugs up and draws a triangle thing
    #vert_list = batch.add(2*len(powers), GL_QUAD_STRIP, None,
    #    ('v2f/static', tuple(quads)), ('c3B/static', tuple(colors)))
    vert_list = pyglet.graphics.vertex_list(2*len(powers),
        ('v2f/static', tuple(quads)), ('c3B/static', tuple(colors)))
    vertexes[now] = vert_list

def change_viewport(x1, x2, y1, y2):
    global viewport
    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    glOrtho(x1, x2, y1, y2, -1, 1)
    glMatrixMode(GL_MODELVIEW)
    #buff = pyglet.image.BufferManager()
    #tuple(pyglet.image.BufferManager.get_viewport(buff))
    # todo - find way of reading viewport
    viewport = (x1, x2, y1, y2)

def text(s, x, y):
    "super hacky"
    vp = viewport
    ratio = ((vp[3]-vp[2])/window.height) / ((vp[1]-vp[0])/window.width)
    label = pyglet.text.Label(s, font_name="Time New Roman", font_size=48,
        x=0, y=0, color=(255,255,255,64),
        anchor_x='center', anchor_y='center')
    verts = []
    for i,v in enumerate(label._vertex_lists[0].vertices):
        if i%2:  # y
            verts.append(v/20 + y)
        else:
            verts.append(v/ratio/20 + x)
    label._vertex_lists[0].vertices = verts
    label.draw()


def update(dt):
    now = time.time() - time_start
    freqs,power = acquire_range(freq_lower, freq_upper)
    render_sample(now, dt, freqs, power)
    window.clear()
    #batch.draw()
    to_pop = []
    for k,v in vertexes.iteritems():
        if k < (now - history):
            to_pop.append(k)
        v.draw(GL_QUAD_STRIP)
    for k in to_pop:
        vertexes[k].delete()
        vertexes.pop(k)
    change_viewport(freq_lower/1e6, freq_upper/1e6, now-history, now)
    vp = viewport
    delta = vp[1] - vp[0]
    text('%0.3fMHz' % (freq_lower/1e6), vp[0]+delta*0.15, now-5)
    text('%0.3fMHz' % (freq_upper/1e6), vp[1]-delta*0.15, now-5)

pyglet.clock.schedule_interval(update, 1/10.0)
pyglet.app.run()


