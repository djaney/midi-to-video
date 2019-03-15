#!/usr/bin/env python3
import argparse
import midi
from midi import constants
import math
import os
from moviepy.editor import CompositeVideoClip, VideoFileClip, clips_array, vfx

FADE_TIME = 0.3

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


def grab_track_by_name(pattern, name):
    """
    :param pattern:
    :param name:
    :return: track
    """
    for track in pattern:
        for event in track:
            if type(event) is midi.TrackNameEvent and event.text == name:
                return track
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
    currently_playing_timeline = []
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

        currently_playing_timeline.append(list(notes_currently_playing.keys()))

    return plan, currently_playing_timeline


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
    for n in range(128):
        note, oct = value_to_note(n)
        note_name = "{}{}".format(note, oct)

        path = None
        for file_type in ['mp4', 'avi']:
            if os.path.isfile("{}/{}{}.{}".format(video_dir, note, oct, file_type)):
                path = "{}/{}{}.{}".format(video_dir, note, oct, file_type)
            if os.path.isfile("{}/{}.{}".format(video_dir, note, file_type)):
                path = "{}/{}.{}".format(video_dir, note, file_type)

        video_map[note_name] = path
    return video_map


def create_video(size, plan, timeline, video_map, notification_callback=None, end=None, start=None):
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

        # lookahead is used to detect events with the same ticks
        # group them together in the video

        if look_ahead == 0:
            look_tick = current_tick
            for look_p in plan[plan_key+1:]:
                if look_tick == look_p[0]:
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
            if duration > 0:
                # cut if not sustain
                if duration >= FADE_TIME > 0:
                    # if duration is long enough, add fade
                    audio = clip.audio
                    audio = audio.subclip(0, duration)
                    clip.set_audio(audio)
                    clip = clip.subclip(0, duration+FADE_TIME)
                    clip = clip.crossfadeout(FADE_TIME)
                else:
                    # otherwise, just cut it
                    clip = clip.subclip(0, duration)
            else:
                # fade out if sustain
                clip = clip.crossfadeout(FADE_TIME)

            clip = clip.resize(size)
            clip = clip.set_start(clip_start)


            # part of a group
            if look_ahead_index != 0 or look_ahead_group_size != 0:
                row_width = math.floor(size[0]/look_ahead_group_size)
                x1 = math.floor((size[0]/2) - (row_width/2))
                clip = vfx.crop(clip, x1=x1, width=row_width)
                clip = clip.set_pos((row_width*look_ahead_index, 0))

            clips.append(clip)
            notification_callback(seconds_in_track, end_time)
            if end is not None and end_time <= seconds_in_track:
                break

    return CompositeVideoClip(clips, bg_color=(0, 0, 255), size=size)


def loader(current, total):
    print("{}/{}".format(current, total))


def main(args):
    pattern = midi.read_midifile(args.midi_path)
    video_map = map_videos(args.video_dir)
    if not args.track:
        print(get_track_names(pattern))
    else:

        total_ticks, resolution, initial_tempo = analyze_midi(pattern)
        track = grab_track_by_name(pattern, args.track)
        event_map = map_events_by_tick(track)
        plan, timeline = generate_track_plan(event_map, resolution, total_ticks, initial_tempo)
        video = create_video((360, 240), plan, timeline, video_map, notification_callback=loader,
                             end=args.end, start=args.start)
        # save
        video.write_videofile(args.output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('midi_path', type=str)
    parser.add_argument('--track', '-t', type=str, default='')
    parser.add_argument('--video_dir', '-d', type=str, default='videos')
    parser.add_argument('--output', '-o', type=str, default='output.mp4')
    parser.add_argument('--start', '-s', type=int, default=None)
    parser.add_argument('--end', '-e', type=int, default=None)
    main(parser.parse_args())
