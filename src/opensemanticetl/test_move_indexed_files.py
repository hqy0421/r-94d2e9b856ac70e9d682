import unittest
from unittest import mock

import json
import itertools

import move_indexed_file


class TestMove(unittest.TestCase):
    def test_move_files(self):
        mock_get_files = mock.Mock(return_value=[
            {'id': 'file:///book1', 'title_t': 'Snow Crash',
             'copies_i': 5, 'cat_ss': ['Science Fiction'],
             'path_basename_s': 'book1', '_version_': 1641756143516647424},
            {'id': 'file:///folder/book2',
             'title_t': 'Other book',
             'copies_i': 3, 'cat_ss': ['Round House Kicks'],
             'path0_s': 'folder',
             'path_basename_s': 'book2', '_version_': 1641756143518744576}])
        mock_post = mock.Mock()

        def mock_prepare(adds, delete_ids):
            self.assertEqual(
                list(adds),
                [
                    {'id': 'file:///snow_crash', 'title_t': 'Snow Crash',
                     'copies_i': 5, 'cat_ss': ['Science Fiction'],
                     'path_basename_s': 'snow_crash'},
                    {'id': 'file:///other_book',
                     'title_t': 'Other book',
                     'copies_i': 3, 'cat_ss': ['Round House Kicks'],
                     'path_basename_s': 'other_book'}])
            self.assertEqual(tuple(delete_ids),
                             ("file:///book1", "file:///folder/book2"))
        with mock.patch("move_indexed_file.get_files", mock_get_files), \
                mock.patch("move_indexed_file.post", mock_post), \
                mock.patch("move_indexed_file.prepare_payload",
                           mock_prepare):
            move_indexed_file.move_files(
                None, {"/book1": "/snow_crash",
                       "/folder/book2": "/other_book"},
                prefix="file://")

    def test_move_dir(self):
        mock_get_files = mock.Mock(return_value=[
            {'id': 'file:///folder/book1', 'title_t': 'Snow Crash',
             'copies_i': 5, 'cat_ss': ['Science Fiction'],
             'path0_s': 'folder',
             'path_basename_s': 'book1', '_version_': 1641756143516647424},
            {'id': 'file:///folder/book2',
             'title_t': 'Other book',
             'copies_i': 3, 'cat_ss': ['Round House Kicks'],
             'path0_s': 'folder',
             'path_basename_s': 'book2', '_version_': 1641756143518744576}])
        mock_post = mock.Mock()

        def mock_prepare(adds, delete_ids):
            self.assertEqual(
                list(adds),
                [
                    {'id': 'file:///dest/book1', 'title_t': 'Snow Crash',
                     'copies_i': 5, 'cat_ss': ['Science Fiction'],
                     'path0_s': 'dest',
                     'path_basename_s': 'book1'},
                    {'id': 'file:///dest/book2',
                     'title_t': 'Other book',
                     'copies_i': 3, 'cat_ss': ['Round House Kicks'],
                     'path0_s': 'dest',
                     'path_basename_s': 'book2'}])
            self.assertEqual(tuple(delete_ids),
                             ("file:///folder/book1", "file:///folder/book2"))
        with mock.patch("move_indexed_file.get_files_in_dir",
                        mock_get_files), \
                mock.patch("move_indexed_file.post", mock_post), \
                mock.patch("move_indexed_file.prepare_payload",
                           mock_prepare):
            move_indexed_file.move_dir(
                None, src="/folder", dest="/dest/",
                prefix="file://")

    def test_move_dirs_parent_and_child(self):
        # /a/b is contained in /a, so the query of /a returns its
        # documents, too: every document has to be moved only once,
        # by the rule with the longest matching source prefix
        doc_a = {'id': 'file:///a/f1', 'title_t': 'Doc 1',
                 'copies_i': 5, 'cat_ss': ['Science Fiction'],
                 'path0_s': 'a', 'path_basename_s': 'f1',
                 '_version_': 1641756143516647424}
        doc_ab = {'id': 'file:///a/b/f2', 'title_t': 'Doc 2',
                  'copies_i': 3, 'cat_ss': ['Round House Kicks'],
                  'path0_s': 'a', 'path1_s': 'b',
                  'path_basename_s': 'f2',
                  '_version_': 1641756143518744576}

        def mock_get_files_in_dir(host, path):
            return {"/a": [doc_a, doc_ab], "/a/b": [doc_ab]}[path]
        mock_get_files = mock.Mock(return_value=[])
        mock_post = mock.Mock()

        def mock_prepare(adds, delete_ids):
            # path1_s of the second document is cleaned up, since the
            # target hierarchy is shorter than the source hierarchy
            self.assertEqual(
                list(adds),
                [{'id': 'file:///x/f1', 'title_t': 'Doc 1',
                  'copies_i': 5, 'cat_ss': ['Science Fiction'],
                  'path0_s': 'x', 'path_basename_s': 'f1'},
                 {'id': 'file:///y/f2', 'title_t': 'Doc 2',
                  'copies_i': 3, 'cat_ss': ['Round House Kicks'],
                  'path0_s': 'y', 'path_basename_s': 'f2'}])
            self.assertEqual(tuple(delete_ids),
                             ("file:///a/f1", "file:///a/b/f2"))
        with mock.patch("move_indexed_file.get_files_in_dir",
                        mock_get_files_in_dir), \
                mock.patch("move_indexed_file.get_files", mock_get_files), \
                mock.patch("move_indexed_file.post", mock_post), \
                mock.patch("move_indexed_file.prepare_payload",
                           mock_prepare):
            move_indexed_file.move_dirs(
                None, {"/a": "/x", "/a/b": "/y"}, prefix="file://")
        mock_get_files.assert_called_once_with(
            None, ["file:///x/f1", "file:///y/f2"])
        mock_post.assert_called_once()

    def test_move_dirs_swap(self):
        # the rules are applied to the original paths only, so two
        # directories can be swapped
        def mock_get_files_in_dir(host, path):
            docs = {
                "/a": [{'id': 'file:///a/f1', 'title_t': 'Doc 1',
                        'path0_s': 'a', 'path_basename_s': 'f1',
                        '_version_': 1641756143516647424}],
                "/b": [{'id': 'file:///b/f2', 'title_t': 'Doc 2',
                        'path0_s': 'b', 'path_basename_s': 'f2',
                        '_version_': 1641756143518744576}]}
            return docs[path]
        mock_get_files = mock.Mock(return_value=[])
        mock_post = mock.Mock()

        def mock_prepare(adds, delete_ids):
            self.assertEqual(
                list(adds),
                [{'id': 'file:///b/f1', 'title_t': 'Doc 1',
                  'path0_s': 'b', 'path_basename_s': 'f1'},
                 {'id': 'file:///a/f2', 'title_t': 'Doc 2',
                  'path0_s': 'a', 'path_basename_s': 'f2'}])
            self.assertEqual(tuple(delete_ids),
                             ("file:///a/f1", "file:///b/f2"))
        with mock.patch("move_indexed_file.get_files_in_dir",
                        mock_get_files_in_dir), \
                mock.patch("move_indexed_file.get_files", mock_get_files), \
                mock.patch("move_indexed_file.post", mock_post), \
                mock.patch("move_indexed_file.prepare_payload",
                           mock_prepare):
            move_indexed_file.move_dirs(
                None, {"/a": "/b", "/b": "/a"}, prefix="file://")
        mock_post.assert_called_once()

    def test_move_dirs_target_is_vacated_old_id(self):
        # the target file:///b/x is the old id of a document which is
        # moved within the same batch, so it is no conflict: the new
        # document is generated from the original record of
        # file:///a/x and only the old id staying unoccupied is
        # deleted
        def mock_get_files_in_dir(host, path):
            docs = {
                "/a": [{'id': 'file:///a/x', 'title_t': 'Doc 1',
                        'path0_s': 'a', 'path_basename_s': 'x',
                        '_version_': 1641756143516647424}],
                "/b": [{'id': 'file:///b/x', 'title_t': 'Doc 2',
                        'path0_s': 'b', 'path_basename_s': 'x',
                        '_version_': 1641756143518744576}]}
            return docs[path]
        mock_get_files = mock.Mock(return_value=[])
        mock_post = mock.Mock()

        def mock_prepare(adds, delete_ids):
            self.assertEqual(
                list(adds),
                [{'id': 'file:///b/x', 'title_t': 'Doc 1',
                  'path0_s': 'b', 'path_basename_s': 'x'},
                 {'id': 'file:///c/x', 'title_t': 'Doc 2',
                  'path0_s': 'c', 'path_basename_s': 'x'}])
            self.assertEqual(tuple(delete_ids), ("file:///a/x",))
        with mock.patch("move_indexed_file.get_files_in_dir",
                        mock_get_files_in_dir), \
                mock.patch("move_indexed_file.get_files", mock_get_files), \
                mock.patch("move_indexed_file.post", mock_post), \
                mock.patch("move_indexed_file.prepare_payload",
                           mock_prepare):
            move_indexed_file.move_dirs(
                None, {"/a": "/b", "/b": "/c"}, prefix="file://")
        # only targets which are no old ids of the batch are checked
        mock_get_files.assert_called_once_with(None, ["file:///c/x"])
        mock_post.assert_called_once()

    def test_move_dirs_conflict_duplicate_targets(self):
        def mock_get_files_in_dir(host, path):
            docs = {
                "/a": [{'id': 'file:///a/f', 'title_t': 'Doc 1',
                        'path0_s': 'a', 'path_basename_s': 'f',
                        '_version_': 1641756143516647424}],
                "/b": [{'id': 'file:///b/f', 'title_t': 'Doc 2',
                        'path0_s': 'b', 'path_basename_s': 'f',
                        '_version_': 1641756143518744576}]}
            return docs[path]
        mock_post = mock.Mock()
        with mock.patch("move_indexed_file.get_files_in_dir",
                        mock_get_files_in_dir), \
                mock.patch("move_indexed_file.get_files",
                           mock.Mock(return_value=[])), \
                mock.patch("move_indexed_file.post", mock_post):
            with self.assertRaises(
                    move_indexed_file.MoveConflictError) as context:
                move_indexed_file.move_dirs(
                    None, {"/a": "/x", "/b": "/x"}, prefix="file://")
        self.assertIn("file:///x/f", str(context.exception))
        mock_post.assert_not_called()

    def test_move_dirs_conflict_target_occupied(self):
        # the target is occupied by a document which is not moved
        # within this batch
        mock_get_files_in_dir = mock.Mock(return_value=[
            {'id': 'file:///a/f', 'title_t': 'Doc 1',
             'path0_s': 'a', 'path_basename_s': 'f',
             '_version_': 1641756143516647424}])
        mock_get_files = mock.Mock(return_value=[
            {'id': 'file:///b/f', 'title_t': 'Other doc',
             'path0_s': 'b', 'path_basename_s': 'f',
             '_version_': 1641756143518744576}])
        mock_post = mock.Mock()
        with mock.patch("move_indexed_file.get_files_in_dir",
                        mock_get_files_in_dir), \
                mock.patch("move_indexed_file.get_files", mock_get_files), \
                mock.patch("move_indexed_file.post", mock_post):
            with self.assertRaises(
                    move_indexed_file.MoveConflictError) as context:
                move_indexed_file.move_dirs(
                    None, {"/a": "/b"}, prefix="file://")
        self.assertIn("file:///b/f", str(context.exception))
        mock_post.assert_not_called()

    def test_get_pages(self):
        step = 3

        original_docs = [{'id': i} for i in range(10)]

        def mock_urlopen():
            docs_iter = iter(original_docs)
            responses = (
                mock_response(
                    {
                        "response": {
                            "numFound": len(original_docs),
                            "docs": list(itertools.islice(docs_iter, step))
                        }
                    }
                )
                for __ in range(0, len(original_docs), step))

            def _mock(*_, **__):
                return next(responses)
            return _mock
        with mock.patch("urllib.request.urlopen",
                        mock_urlopen()):
            docs = sum(move_indexed_file.get_pages("", "", limit=step), [])
        self.assertEqual(docs, original_docs)


def mock_response(data):
    return type("MockResponse", (object,), {
        "read": json.dumps(data).encode})
