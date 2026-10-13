# SPDX-License-Identifier: GPL-2.0-or-later
"""Bpy-only adapter for the isolated weather service; identities, generations and pacing."""
import os
import time
from datetime import datetime
from . import model, groups, session
from blui_explorer.localization import iface

_pending = {}
_next = {}


def queue(runtime, tree, node, force=True):
    key = (runtime.identity(tree), node.name, node.weather_generation)
    if key in _pending.values():
        return
    args = {'latitude': node.latitude, 'longitude': node.longitude,
            'cache_directory': os.path.join(session.storage_directory(), 'weather'),
            'source': node.weather_source, 'force': force}
    job = runtime.submit('weather', tree, args)
    _pending[id(job)] = key
    _next[key[:2]] = time.monotonic() + 900
    node.weather_status = 'Loading...'


def receive(runtime, job, value):
    key = _pending.pop(id(job), None)
    if not key:
        return
    token, name, generation = key
    tree = runtime.resolve_tree(token)
    node = tree.nodes.get(name) if tree else None
    if not node or node.bl_idname != model.WEATHER or node.weather_generation != generation:
        return
    data = value['data']
    node.weather_stale, node.weather_error = value['stale'], value['error']
    node.weather_status = 'Offline weather cache' if value['stale'] else ''
    if data:
        node.temperature = f"{data['temperature']:.1f} °C"
        node.condition = data['condition']
        node.humidity = str(data['humidity']) + ' %'
        node.wind_speed = str(data['wind_speed']) + ' km/h'
        node.observed_at = data['observed_at']
        node.updated_at = datetime.fromtimestamp(data['fetched_at']).strftime('%m-%d %H:%M')


def failed(runtime, job, message):
    key = _pending.pop(id(job), None)
    if key:
        tree = runtime.resolve_tree(key[0])
        node = tree.nodes.get(key[1]) if tree else None
        if node and node.bl_idname == model.WEATHER:
            node.weather_error = 'Weather service is unavailable'
            node.weather_status = ''


def tick(runtime):
    now = time.monotonic()
    for root in session.roots():
        for tree in groups.trees(root):
            for node in tree.nodes:
                if node.bl_idname == model.WEATHER and node.weather_enabled:
                    key = (runtime.identity(tree), node.name)
                    if now >= _next.get(key, 0):
                        try:
                            queue(runtime, tree, node, force=False)
                        except RuntimeError:
                            return


def reset():
    _pending.clear()
    _next.clear()
