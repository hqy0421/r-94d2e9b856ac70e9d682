#!/usr/bin/env python3

import urllib.request
import urllib.parse
import json
from collections import Counter
from itertools import starmap


def move_files(host: str, moves: dict, prefix=""):
    """Moves files within the index (not physically).

    Example of usage:
    host = "http://solr:8983/solr/opensemanticsearch/"
    move_files(host, {"/b2": "/book2",
                      "/b1": "/folder/book1"}, prefix="file://")


    :host: Url to the solr instance
    :moves: A dict of the form {src: dest, ...}, where src is
            the source path and dest is the destination path.
    """
    src = moves.keys()
    indexed_data = get_files(host, map(append_prefix(prefix), src))
    # In the following we have to remap the destination path to
    # the individual metadata entries, since the ordering of
    # the query result and query may differ:
    moved_data = starmap(change_path(prefix),
                         zip(indexed_data,
                             map(dict_map(moves),
                                 map(extract_path,
                                     indexed_data))))
    request_payload = prepare_payload(
        moved_data, (d["id"] for d in indexed_data))
    post(host, request_payload)


def move_dir(host: str, src: str, dest: str, prefix=""):
    """Moves directories within the index (not physically).

    Example of usage:
    host = "http://solr:8983/solr/opensemanticsearch/"
    move_dir(host, src=/docs/a/, dest=/docs/b, prefix="file://")


    :host: Url to the solr instance
    :src: Source directory
    :dest: Destination directory
    """
    indexed_data = get_files_in_dir(host, src)
    moved_data = map(change_dir(prefix, src=src, dest=dest),
                     indexed_data)
    request_payload = prepare_payload(
        moved_data, (d["id"] for d in indexed_data))
    post(host, request_payload)


class MoveConflictError(ValueError):
    """Conflicts were detected while planning a batch directory
    move, so no update was sent to the index
    """
    def __init__(self, conflicts):
        super().__init__(
            "Conflicting batch directory move, index not updated:\n"
            + "\n".join(conflicts))
        self.conflicts = conflicts


def move_dirs(host: str, moves: dict, prefix=""):
    """Moves multiple directories within the index (not physically)
    in one batch.

    Each document is mapped exactly once: its original (not yet
    rewritten) path is matched segment wise against the source
    directories and only the rule with the longest matching source
    prefix is applied. Therefore parent and child directories can be
    moved within the same batch and two directories can be swapped,
    without rules being applied to paths already rewritten by another
    rule.

    The whole batch is planned before anything is written: if
    multiple documents would be moved to the same target or a target
    is occupied by a document which is not moved within this batch,
    a MoveConflictError is raised and no update is sent. Targets
    which are old ids of documents moved (and thereby vacated) within
    this batch are allowed: the new documents are generated from the
    original records and afterwards only old ids which stay
    unoccupied are deleted.

    Example of usage:
    host = "http://solr:8983/solr/opensemanticsearch/"
    move_dirs(host, {"/archive/a": "/archive/b",
                     "/archive/b": "/archive/a"}, prefix="file://")

    :host: Url to the solr instance
    :moves: A dict of the form {src_dir: dest_dir, ...}
    :prefix: Prefix of the id, e.g. "file://"
    """
    moves_by_segments = {}
    for src, dest in moves.items():
        src_segments = tuple(src.strip("/").split("/"))
        if src_segments in moves_by_segments:
            raise ValueError("Duplicate source directory: " + src)
        moves_by_segments[src_segments] = dest.strip("/").split("/")
    indexed_data = get_files_in_dirs(host, moves)
    moved_data = list(map(change_dirs_once(prefix, moves_by_segments),
                          indexed_data))
    old_ids = [doc["id"] for doc in indexed_data]
    new_ids = [doc["id"] for doc in moved_data]
    conflicts = find_conflicts(host, old_ids, new_ids)
    if conflicts:
        raise MoveConflictError(conflicts)
    # Old ids which are reused as a target get overwritten by the new
    # documents, so only old ids staying unoccupied have to be deleted
    new_ids_set = set(new_ids)
    delete_ids = [old_id for old_id in old_ids if old_id not in new_ids_set]
    if moved_data:
        post(host, prepare_payload(moved_data, delete_ids))


def change_path(prefix: str):
    """Returns a mapping function to be used with starmap
    """
    def change(data: dict, dest: str) -> dict:
        """Creates a modified version of data

        :data: The indexed metadata of the moved file
        :dest: The destination path
        """
        dest_components = dest.strip("/").split("/")
        return _change_path(data, dest_components, prefix=prefix)
    return change


def change_dir(prefix: str, src: str, dest: str):
    """Returns a mapping function to be used with map
    """
    dest_components = dest.strip("/").split("/")
    src_path_components = src.strip("/").split("/")

    def change(data: dict) -> dict:
        """Creates a modified version of data

        :data: The indexed metadata of the moved file
        :dest: The destination path
        """
        indexed_components = extract_path_components(data)
        # Attention: zip consumes the generator up to the number
        # of elements in indexed_components. If you switch the two
        # arguments of zip, an additional element will be consumed
        # from indexed_components, as zip will perform a next on
        # its first argument to see if the iterable is exhausted.
        for idx_component, src_component in zip(src_path_components,
                                                indexed_components):
            if idx_component != src_component:
                raise ValueError(
                    "Path component of file and input file differs: '"
                    + idx_component + "' <-> '" + src_component + "'")
        return _change_path(data, dest_components + list(indexed_components),
                            prefix=prefix)
    return change


def change_dirs_once(prefix: str, moves_by_segments: dict):
    """Returns a mapping function to be used with map, applying the
    single move rule whose source directory is the longest segment
    wise prefix of the original path of the document
    """
    def change(data: dict) -> dict:
        """Creates a modified version of data

        :data: The indexed metadata of the moved file
        """
        path_segments = list(extract_path_components(data))
        src_segments, dest_segments = longest_prefix_match(
            path_segments, moves_by_segments)
        return _change_path(
            data, dest_segments + path_segments[len(src_segments):],
            prefix=prefix)
    return change


def longest_prefix_match(path_segments: list, moves_by_segments: dict):
    """Returns the (source, destination) segments of the move rule
    whose source directory is the longest segment wise prefix of
    :path_segments:
    """
    match = None
    for src_segments, dest_segments in moves_by_segments.items():
        if (tuple(path_segments[:len(src_segments)]) == src_segments
                and (match is None
                     or len(src_segments) > len(match[0]))):
            match = (src_segments, dest_segments)
    if match is None:
        raise ValueError("No move rule matches path: /"
                         + "/".join(path_segments))
    return match


def _change_path(data: dict, dest_components: tuple, prefix: str = "") -> dict:
    """Creates a modified version of data

    :data: The indexed metadata of the moved file
    :dest_components: The destination path split into components
    """
    moved_data = data.copy()
    del moved_data["_version_"]
    moved_data["id"] = prefix + "/" + "/".join(dest_components)
    *dest_dir_components, base_name = dest_components
    moved_data.update({"path{}_s".format(i): component
                       for i, component in enumerate(dest_dir_components)})
    moved_data["path_basename_s"] = base_name
    n = len(dest_dir_components)
    while True:
        if moved_data.pop("path{}_s".format(n), None) is None:
            break
        n += 1
    return moved_data


def prepare_payload(adds, delete_ids):
    """Takes metadata to be added to the index and ids to be deleted
    from the index. Creates the corresponding solr json request payload
    """
    payload = {DuplicateKey("add"): {"doc": doc} for doc in adds}
    payload["delete"] = [
        {"id": id_} for id_ in delete_ids]
    return payload


def find_conflicts(host: str, old_ids: list, new_ids: list) -> list:
    """Checks the plan of a batch directory move, returning a list of
    conflict descriptions (empty if the plan is consistent)
    """
    conflicts = []
    duplicates = sorted(id_ for id_, count in Counter(new_ids).items()
                        if count > 1)
    if duplicates:
        conflicts.append(
            "Multiple documents moved to the same target: "
            + ", ".join(duplicates))
    # Targets which are old ids of this batch get vacated by the
    # batch itself, only other targets must not be occupied
    foreign_targets = sorted(set(new_ids) - set(old_ids))
    if foreign_targets:
        occupied = sorted(doc["id"]
                          for doc in get_files(host, foreign_targets))
        if occupied:
            conflicts.append(
                "Target occupied by document which is not moved: "
                + ", ".join(occupied))
    return conflicts


class DuplicateKey(str):
    """Allows dicts having multiple identical keys"""

    def __hash__(self):
        return id(self)


def extract_path(data: dict) -> str:
    """Extracts the path of the metadata
    """
    return "/" + "/".join(extract_path_components(data))


def extract_path_components(data: dict):
    """Extracts the path of the metadata in form of a
    generator yielding the components of the path
    """
    i = 0
    while True:
        component = data.get("path{}_s".format(i))
        if component is None:
            break
        yield component
        i += 1
    yield data["path_basename_s"]


def dict_map(mapping: dict):
    """Converts a dict into a function (for usage with map)"""
    def _map(s):
        return mapping[s]
    return _map


def append_prefix(prefix: str):
    """A mapping function to be used with :map:"""
    def append(s: str):
        return prefix + s
    return append


def get_files(host: str, ids: list) -> list:
    """Queries solr, searches for files whose id is in :ids:"""
    return get(host,
               "(" + ", ".join(
                   map('id:"{}"'.format, ids)) + ")"
               )


def get_files_in_dir(host: str, path: str) -> list:
    """Queries solr, searches for files in the folder :path:"""
    path_components = path.strip("/").split("/")
    return get(host,
               " AND ".join(
                   starmap(
                       'path{}_s:"{}"'.format, enumerate(path_components)
                   )))


def get_files_in_dirs(host: str, srcs) -> list:
    """Queries solr, searches for files in the folders :srcs:.

    Each document is returned only once, even if a source directory
    is contained in another source directory.
    """
    docs = {}
    for src in srcs:
        for doc in get_files_in_dir(host, src):
            docs[doc["id"]] = doc
    return list(docs.values())


def get(host: str, query: str) -> list:
    return sum(get_pages(host, query), [])


def get_pages(host: str, query: str, limit=50):
    """An iterator over the pages of a solr request response"""
    start = 0
    n_docs = limit
    query_url_template = host + "select?start={}&rows={}&q={}".format(
        "{}", limit, urllib.parse.quote(query))
    while start < n_docs:
        response = urllib.request.urlopen(
            query_url_template.format(start))
        data = json.loads(response.read().decode())["response"]
        n_docs = data["numFound"]
        start += limit
        yield data["docs"]


def post(host: str, data: dict):
    request = urllib.request.Request(
        host + "update/json?commit=true",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(request)
