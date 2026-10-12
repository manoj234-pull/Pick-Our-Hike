"""US display defaults; explicit user units override them. Calculations stay metric."""
from dataclasses import dataclass
from datetime import time
import re


def _number(value: float) -> str:
    return f'{value:.2f}'.rstrip('0').rstrip('.')


@dataclass
class DisplayFormat:
    miles: bool = True
    feet: bool = True
    twelve_hour: bool = True

    @classmethod
    def from_trip(cls, trip):
        return cls(miles=(trip.get('distance_unit') or 'miles') == 'miles',
                   feet=(trip.get('elevation_unit') or 'ft') == 'ft',
                   twelve_hour=(trip.get('clock_format') or '12h') == '12h')

    def distance(self, km: float) -> str:
        return f'{_number(km / 1.609344 if self.miles else km)} {"miles" if self.miles else "km"}'

    def elevation(self, metres: float) -> str:
        return f'{_number(metres / .3048 if self.feet else metres)} {"ft" if self.feet else "m"}'

    def duration(self, minutes: float) -> str:
        if minutes < 60:
            return f'{_number(minutes)} min'
        hours, remainder = divmod(round(minutes, 2), 60)
        return f'{int(hours)} hr' + (f' {_number(remainder)} min' if remainder else '')

    def pace(self, minutes_per_km: float) -> str:
        return f'{_number(minutes_per_km * 1.609344 if self.miles else minutes_per_km)} min/{"mile" if self.miles else "km"}'

    def clock(self, value: time | str) -> str:
        value = time.fromisoformat(value) if isinstance(value, str) else value
        if not self.twelve_hour:
            return value.strftime('%H:%M')
        minutes = f':{value.minute:02}' if value.minute else ''
        return f'{value.hour % 12 or 12}{minutes} {"AM" if value.hour < 12 else "PM"}'

    def text(self, text: str) -> str:
        """Format app-authored check/default strings, never source URLs or model JSON."""
        number = r'\d+(?:\.\d+)?'
        # Expand shared units on compromise ranges before converting both endpoints.
        text = re.sub(rf'({number}) -> ({number}) (km|m)\b', r'\1 \3 -> \2 \3', text)
        tokens = []
        def save(value):
            tokens.append(value)
            return f'@@{len(tokens)-1}@@'
        text = re.sub(rf'({number}) (?:minutes|min)/km\b', lambda m: save(self.pace(float(m[1]))), text)
        text = re.sub(rf'({number}) km\b', lambda m: self.distance(float(m[1])), text)
        text = re.sub(rf'({number}) m\b', lambda m: self.elevation(float(m[1])), text)
        text = re.sub(r'\b([01]\d|2[0-3]):[0-5]\d\b', lambda m: self.clock(m[0]), text)
        text = re.sub(rf'({number}) (?:minutes|min)\b(?!/| per\b)',
                      lambda m: self.duration(float(m[1])), text)
        for index, value in enumerate(tokens):
            text = text.replace(f'@@{index}@@', value)
        return text
