#!/usr/bin/env python3
import argparse
import midi
from midi import constants
import math
import time


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
    seconds_per_tick = calculate_seconds_per_tick(initial_tempo, resolution)
    max_stack = 0
    for current_tick in range(max_ticks):
        if current_tick not in event_map:
            continue


        events = event_map[current_tick]
        max_stack = max(len(events), max_stack)
        for event in events:
            if type(event) is midi.TrackNameEvent:
                track_name = event.text
                print(track_name)
            elif type(event) is midi.SetTempoEvent:
                seconds_per_tick = calculate_seconds_per_tick(event.get_bpm(), resolution)
            elif type(event) is midi.NoteOnEvent:
                note, octave = value_to_note(event.get_pitch())
                seconds_in_track = seconds_per_tick * current_tick
                plan.append((seconds_in_track, note, octave, 0))
                key = "{}{}-{}".format(note, octave, event.channel)
                notes_currently_playing[key] = len(plan) - 1
            elif type(event) is midi.NoteOffEvent:
                note, octave = value_to_note(event.get_pitch())
                key = "{}{}-{}".format(note, octave, event.channel)
                current_seconds_in_track = seconds_per_tick * current_tick
                if key in notes_currently_playing:
                    note_index = notes_currently_playing[key]
                    seconds_in_track, note, octave, duration = plan[note_index]
                    duration = current_seconds_in_track - seconds_in_track
                    plan[note_index] = (seconds_in_track, note, octave, duration)
                    del notes_currently_playing[key]
    for p in plan:
        seconds_in_track, note, octave, duration = p
        if duration == 0:
            duration = "sustain"
            print("[{:.4f}] Play {}{} {}".format(seconds_in_track, note, octave, duration))
        else:
            print("[{:.4f}] Play {}{} for {:.4f} seconds".format(seconds_in_track, note, octave, duration))



def main(args):
    pattern = midi.read_midifile(args.midi_path)
    resolution = pattern.resolution

    if not args.track:
        print(get_track_names(pattern))
    else:

        max_ticks, resolution, initial_tempo = analyze_midi(pattern)
        track = grab_track_by_name(pattern, args.track)
        event_map = map_events_by_tick(track)
        generate_track_plan(event_map, resolution, max_ticks, initial_tempo)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('midi_path', type=str)
    parser.add_argument('--track', type=str, default='')
    main(parser.parse_args())
