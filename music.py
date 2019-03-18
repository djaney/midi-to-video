#!/usr/bin/env python3
import argparse
import midi
from midi import constants
import math
import os
from moviepy.editor import CompositeVideoClip, VideoFileClip, concatenate_videoclips, vfx
import warnings

MIN_DURATION = 0.3

def value_to_note(value):
    noteidx = value % constants.NOTE_PER_OCTAVE
    octidx = math.floor(value / constants.OCTAVE_MAX_VALUE)
    name = constants.NOTE_NAMES[noteidx]
    return name, octidx


def analyze_midi(pattern):
    """
    :param pattern: 
    :return: max_ticks, resolution , initial_tempo
    """
    max_ticks = 0
    initial_tempo = None
    for track in pattern:
        total = 0
        for event in track:
            if type(event) is midi.SetTempoEvent and initial_tempo is None:
                initial_tempo = event.get_bpm()
            total += event.tick
        max_ticks = max(total, max_ticks)

    return max_ticks, pattern.resolution, initial_tempo


def grab_track_by_index(pattern, index):
    """
    :param pattern:
    :param name:
    :return: track
    """
    if index < len(pattern):
        return pattern[index]
    return None


def get_track_names(pattern):
    """
    :param pattern:
    :return: list
    """
    names = []
    for track in pattern:
        for event in track:
            if type(event) is midi.TrackNameEvent:
                names.append(event.text)
                break

    return names


def map_events_by_tick(track):
    """
    :param track:
    :return: dict
    """
    event_map = {}
    current_tick = 0
    for event in track:
        current_tick += event.tick
        if current_tick not in event_map:
            event_map[current_tick] = []
        event_map[current_tick].append(event)
    return event_map


def calculate_seconds_per_tick(tempo, resolution):
    """
    Calculate the seconds equivalent of every tick
    :param tempo:
    :param resolution:
    :return:
    """
    return 60 * 1000000 / tempo / resolution / 1000000


def generate_track_plan(event_map, resolution, max_ticks, initial_tempo):
    plan = []
    notes_currently_playing = {}
    seconds_per_tick = calculate_seconds_per_tick(initial_tempo, resolution)
    max_stack = 0
    for current_tick in range(max_ticks):
        if current_tick in event_map:
            events = event_map[current_tick]
            max_stack = max(len(events), max_stack)
            for event in events:
                if type(event) is midi.SetTempoEvent:
                    seconds_per_tick = calculate_seconds_per_tick(event.get_bpm(), resolution)
                elif type(event) is midi.NoteOnEvent:
                    note, octave = value_to_note(event.get_pitch())
                    turn_on_note(note, octave, event.channel, seconds_per_tick, current_tick, plan,
                                 notes_currently_playing, event.get_velocity())
                elif type(event) is midi.NoteOffEvent:
                    note, octave = value_to_note(event.get_pitch())
                    turn_off_note(note, octave, event.channel, seconds_per_tick, current_tick, plan,
                                  notes_currently_playing)

    return plan


def get_note_key(note, octave, channel):
    return "{}{}-{}".format(note, octave, channel)


def turn_on_note(note, octave, channel, seconds_per_tick, current_tick, plan, notes_currently_playing, velocity):
    seconds_in_track = seconds_per_tick * current_tick
    key = get_note_key(note, octave, channel)

    # turn off not if already playing
    if key in notes_currently_playing:
        note_index = notes_currently_playing[key]
        t, s, n, o, d, v = plan[note_index]
        turn_off_note(n, o, channel, seconds_per_tick, current_tick, plan, notes_currently_playing)

    plan.append((current_tick, seconds_in_track, note, octave, 0, velocity))
    notes_currently_playing[key] = len(plan) - 1


def turn_off_note(note, octave, channel, seconds_per_tick, current_tick, plan, notes_currently_playing):
    key = get_note_key(note, octave, channel)
    current_seconds_in_track = seconds_per_tick * current_tick
    if key in notes_currently_playing:
        note_index = notes_currently_playing[key]
        current_tick, seconds_in_track, note, octave, duration, velocity = plan[note_index]
        duration = current_seconds_in_track - seconds_in_track
        plan[note_index] = (current_tick, seconds_in_track, note, octave, duration, velocity)
        notes_currently_playing.pop(key)


def map_videos(video_dir):
    video_map = {}
    mid = 3
    for n in range(128):
        note, oct = value_to_note(n)
        note_name = "{}{}".format(note, oct)
        file_type = "mp4"
        path = None
        if os.path.isfile("{}/{}{}.{}".format(video_dir, note, oct, file_type)):
            path = "{}/{}{}.{}".format(video_dir, note, oct, file_type)
        elif os.path.isfile("{}/{}.{}".format(video_dir, note, file_type)):
            path = "{}/{}.{}".format(video_dir, note, file_type)
        elif oct <= mid:
            for i in range(oct, mid+1):
                if os.path.isfile("{}/{}{}.{}".format(video_dir, note, i, file_type)):
                    path = "{}/{}{}.{}".format(video_dir, note, i, file_type)
                    break
        elif oct > mid:
            for i in range(oct, mid, -1):
                if os.path.isfile("{}/{}{}.{}".format(video_dir, note, i, file_type)):
                    path = "{}/{}{}.{}".format(video_dir, note, i, file_type)
                    break

        if path is not None:
            video_map[note_name] = path
        else:
            warnings.warn("{}{} missing, unable to map".format(note, oct), RuntimeWarning)

    return video_map


def create_video(size, plan, video_map, notification_callback=None, end=None, start=None, combine_threashold=0,
                 fade_time=0, volumex=2, bg=(0,0,0), shift_octave=0):
    clips = []
    if end is not None and end < len(plan):
        end_time = end
    else:
        # time of last frame
        end_time = plan[-1][1]

    look_ahead = 0
    video_combination_pool = []
    look_ahead_group_size = 0
    for plan_key, (current_tick, seconds_in_track, note, octave, duration, velocity) in enumerate(plan):

        if start is not None and seconds_in_track < start:
            continue

        # shift octave
        octave += shift_octave

        # lookahead is used to detect events with the same ticks
        # group them together in the video

        if look_ahead == 0:
            look_tick = current_tick
            for look_p in plan[plan_key+1:]:
                if abs(look_tick - look_p[0]) < combine_threashold:
                    look_ahead += 1
                else:
                    break
            if look_ahead > 0:
                # This is the size of the group of videos
                look_ahead += 1
                look_ahead_group_size = look_ahead
        else:
            look_ahead -= 1

        if look_ahead > 0:

            look_ahead_index = look_ahead_group_size-look_ahead
        else:
            look_ahead_group_size = 0
            look_ahead_index = 0

        # of lookahead > 0 then it's still a part of the group

        video_key = "{}{}".format(note, octave)
        if video_key in video_map:
            # get a fragment of the clip
            if start is not None:
                clip_start = seconds_in_track - start
            else:
                clip_start = seconds_in_track
            if clip_start < 0:
                clip_start = 0

            clip = VideoFileClip(video_map[video_key])

            # minimum duration
            if duration > MIN_DURATION:
                duration = MIN_DURATION

            # avoid going under the clip duration
            if clip.duration < duration:
                duration = clip.duration

            # add volume via velocity
            volume = velocity / 127 * volumex
            clip = clip.volumex(volume)

            if duration > 0:
                # cut if not sustain
                if duration >= fade_time > 0 and duration+fade_time > clip.duration:
                    # if duration is long enough, add fade
                    audio = clip.audio
                    audio = audio.subclip(0, duration)
                    clip.set_audio(audio)
                    clip = clip.subclip(0, duration+fade_time)
                    clip = clip.crossfadeout(fade_time)
                elif clip.duration < duration:
                    # otherwise, just cut it
                    clip = clip.subclip(0, duration)
            else:
                # fade out if sustain
                clip = clip.crossfadeout(fade_time)

            clip = clip.resize(size)
            clip = clip.set_start(clip_start)

            # part of a group
            if look_ahead_index != 0 or look_ahead_group_size != 0:
                row_width = math.floor(size[0]/look_ahead_group_size)
                x1 = math.floor((size[0]/2) - (row_width/2))
                clip = vfx.crop(clip, x1=x1, width=row_width)
                clip = clip.set_pos((row_width*look_ahead_index, 0))

            clips.append(clip)
            notification_callback(seconds_in_track if start is None else math.floor(seconds_in_track-start),
                                  end_time if start is None else math.floor(end_time - start))
            if end is not None and end_time <= seconds_in_track:
                break
        else:
            warnings.warn("Unable to play {}, file not mapped".format(video_key))

    composite = CompositeVideoClip(clips, bg_color=bg, size=size)

    return composite


def loader(current, total):
    print("{:.02f}%".format(current / total * 100))

def hex_to_rgb(colorstring):
    """ convert #RRGGBB to an (R, G, B) tuple """
    colorstring = colorstring.strip()
    if colorstring[0] == '#': colorstring = colorstring[1:]
    if len(colorstring) != 6:
        raise ValueError( "input #{} is not in #RRGGBB format".format(colorstring) )
    r, g, b = colorstring[:2], colorstring[2:4], colorstring[4:]
    r, g, b = [int(n, 16) for n in (r, g, b)]
    return (r, g, b)


def test_videos(video_map):
    clips = []
    for v in video_map.values():
        clips.append(VideoFileClip(v))
    video = concatenate_videoclips(clips)
    video.write_videofile("test.mp4")

def main(args):
    pattern = midi.read_midifile(args.midi_path)
    video_map = map_videos(args.video_dir)

    if args.test:
        test_videos(video_map)
    elif args.track <= 0:
        print(get_track_names(pattern))
    else:

        total_ticks, resolution, initial_tempo = analyze_midi(pattern)
        track = grab_track_by_index(pattern, args.track)

        print(get_track_names(pattern)[args.track - 1])

        event_map = map_events_by_tick(track)
        plan = generate_track_plan(event_map, resolution, total_ticks, initial_tempo)
        video = create_video((360, 240), plan, video_map,
                             notification_callback=loader,
                             end=args.end, start=args.start,
                             combine_threashold=args.combine_tick_threshold,
                             fade_time=args.fade_time,
                             volumex=args.volumex, 
                             bg=hex_to_rgb(args.bg),
                             shift_octave=args.shift_octave)
        # save
        video.write_videofile(args.output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('midi_path', type=str)
    parser.add_argument('--track', '-t', type=int, default=-1)
    parser.add_argument('--video_dir', '-d', type=str, default='videos')
    parser.add_argument('--output', '-o', type=str, default='output.mp4')
    parser.add_argument('--start', '-s', type=int, default=None)
    parser.add_argument('--end', '-e', type=int, default=None)
    parser.add_argument('--fade_time', '-f', type=float, default=.03)
    parser.add_argument('--combine_tick_threshold', '-c', type=int, default=100)
    parser.add_argument('--volumex', type=float, default=2)
    parser.add_argument('--test', action='store_true')
    parser.add_argument('--bg', default="000000", type=str)
    parser.add_argument('--shift_octave', default=0, type=int)
    main(parser.parse_args())
