# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from verselatch_app.files import FileService, LyricsDocument, SaveReceipt, SaveRequest
from verselatch_app.session import SourceIdentity


class FakeFiles:
    def __init__(self, current: SourceIdentity) -> None:
        self.current = current
        self.saved: list[SaveRequest] = []

    def revalidate(self, source: SourceIdentity) -> bool:
        return source == self.current

    def read_lyrics(self, source: SourceIdentity) -> LyricsDocument:
        return LyricsDocument(source=source, text="line one\nline two\n")

    def save_reviewed_lrc(self, request: SaveRequest) -> SaveReceipt:
        self.saved.append(request)
        return SaveReceipt(
            output=SourceIdentity("content://documents/output.lrc", 1),
            backup=SourceIdentity("content://documents/output.lrc.bak", 1),
        )


def test_file_service_keeps_locations_opaque() -> None:
    audio = SourceIdentity("content://media/audio/42", ("generation", 7))
    lyrics = SourceIdentity("content://documents/lyrics", ("generation", 3))
    files = FakeFiles(audio)

    assert isinstance(files, FileService)
    assert files.revalidate(audio) is True
    assert files.revalidate(lyrics) is False
    document = files.read_lyrics(lyrics)
    assert document.source == lyrics
    assert document.text == "line one\nline two\n"

    request = SaveRequest(
        content="[00:01.00]line one\n",
        audio=audio,
        lyrics=lyrics,
    )
    receipt = files.save_reviewed_lrc(request)
    assert files.saved == [request]
    assert receipt.output.location.startswith("content://")
    assert receipt.backup is not None


def test_file_service_is_not_a_generic_filesystem_api() -> None:
    public_methods = {
        name for name in FileService.__dict__
        if not name.startswith("_")
    }
    assert public_methods == {"revalidate", "read_lyrics", "save_reviewed_lrc"}
