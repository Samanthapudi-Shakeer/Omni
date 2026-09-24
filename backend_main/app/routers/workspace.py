from __future__ import annotations
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
import aiofiles
import zipfile
import shutil
import json
from datetime import datetime

from app import config
from app.models import WorkspaceFile

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


class CreateWorkspaceFileRequest(BaseModel):
    name: str
    content: str = ""


@router.get("/{workspace}/files", response_model=List[WorkspaceFile])
async def list_files(workspace: str):
    try:
        ws = config.workspace_dir(workspace)
    except ValueError as e:
        raise HTTPException(400, str(e))

    out = []
    for p in sorted(path for path in ws.rglob("*") if path.is_file()):
        if any(part.startswith(".ac_") for part in p.relative_to(ws).parts):
            continue
        out.append(WorkspaceFile(
            name=str(p.relative_to(ws)),
            size_bytes=p.stat().st_size,
            is_generated=p.name.startswith(("fix_", "modularized_")),
        ))
    return out


@router.post("/{workspace}/upload", response_model=WorkspaceFile)
async def upload_file(workspace: str, file: UploadFile = File(...)):
    try:
        dest = config.safe_file_path(workspace, file.filename)
    except ValueError as e:
        raise HTTPException(400, str(e))

    async with aiofiles.open(dest, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            await out.write(chunk)

    return WorkspaceFile(name=dest.name, size_bytes=dest.stat().st_size)


@router.post("/{workspace}/file", response_model=WorkspaceFile)
async def create_file(workspace: str, request: CreateWorkspaceFileRequest):
    try:
        dest = config.safe_file_path(workspace, request.name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if dest.exists():
        raise HTTPException(409, "File already exists")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(request.content, encoding="utf-8")
    return WorkspaceFile(name=str(dest.relative_to(config.workspace_dir(workspace))),
                         size_bytes=dest.stat().st_size)


@router.delete("/{workspace}/file/{filename:path}")
async def delete_file(workspace: str, filename: str):
    try:
        path = config.safe_file_path(workspace, filename)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "File not found")
    path.unlink()
    return {"name": filename, "deleted": True}


@router.post("/{workspace}/upload-zip", response_model=List[WorkspaceFile])
async def upload_zip(workspace: str, file: UploadFile = File(...)):
    """Extract a project archive into the workspace for SonarQube analysis."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "A .zip project archive is required")
    try:
        ws = config.workspace_dir(workspace)
    except ValueError as e:
        raise HTTPException(400, str(e))

    archive = ws / ".ac_project.zip"
    try:
        async with aiofiles.open(archive, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                await out.write(chunk)
        extracted: list[Path] = []
        root = ws.resolve()
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                member_path = Path(member.filename)
                target = (ws / member_path).resolve()
                if member_path.is_absolute() or (target != root and root not in target.parents):
                    raise HTTPException(400, f"Unsafe ZIP entry: {member.filename}")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as source, target.open("wb") as dest:
                    shutil.copyfileobj(source, dest)
                extracted.append(target)
    except zipfile.BadZipFile:
        raise HTTPException(400, "Uploaded file is not a valid ZIP archive")
    finally:
        archive.unlink(missing_ok=True)

    manifest = [
        str(path.relative_to(root))
        for path in extracted
        if path.is_file()
    ]
    (ws / ".ac_project_files.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    (ws / ".ac_project_metadata.json").write_text(
        json.dumps({
            "zip_name": Path(file.filename or "uploaded-project.zip").stem,
            "uploaded_date": datetime.now().strftime("%d_%m_%Y"),
        }),
        encoding="utf-8",
    )

    return [
        WorkspaceFile(name=str(path.relative_to(root)), size_bytes=path.stat().st_size)
        for path in extracted
    ]


@router.get("/{workspace}/download/{filename}")
async def download_file(workspace: str, filename: str):
    from fastapi.responses import FileResponse
    try:
        path = config.safe_file_path(workspace, filename)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(path, filename=filename)
