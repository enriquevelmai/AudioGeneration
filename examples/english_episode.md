---
title: Local Voices - Episode 1
lang: en
default_voice: emma
paragraph_pause: 0.5
---

# Local Voices - Episode 1
# An English-only example with the sample voices "emma" (F5-TTS) and "david" (XTTS v2).
# This is the main example script: tags are [voice:], [pause:], [music:] and [sfx:].
# Lines starting with "#" are comments and are not spoken.
# To add music, remove the "#" from the [music:...] lines and put your own files in
# examples/assets/ (paths are relative to this script).

# [music:assets/intro.mp3 vol=0.6 fade=1]
# [music:assets/background.mp3 bg vol=0.12 fade=2]

[voice:emma]
Hello and welcome to Local Voices, the show where every word you hear is generated on a
single home computer. I'm Emma.

[voice:david]
And I'm David. Today we're answering one question: how do you turn a plain text file into
a podcast episode?

[pause:0.8]

[voice:emma]
It starts with a script, just like this one. You write the dialogue in Markdown, and you
mark who is speaking with a short tag.

[voice:david speed=0.95]
Then you add pauses, background music or sound effects wherever you need them. The program
reads the script, synthesizes every sentence and mixes everything together.

# [sfx:assets/ding.wav vol=0.7]

[voice:emma]
And if you change a single line, only that sentence is generated again. Everything else
comes straight from the cache.

[pause:1]

[voice:david]
That's all for today. Thanks for listening.

[voice:emma]
See you next time!

[pause:1.5]
# [music:stop fade=3]
