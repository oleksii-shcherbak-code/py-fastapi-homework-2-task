from datetime import date, timedelta
from math import ceil

from pydantic import ValidationError
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from database.models import (
    MovieModel, CountryModel, GenreModel, ActorModel, LanguageModel
)
from schemas.movies import (
    MovieListResponseSchema, MovieCreateSchema,
    MovieDetailSchema, MovieUpdateSchema
)

router = APIRouter(prefix="/movies", tags=["Movies"])

BASE_URL = "/theater/movies"


async def get_or_create(db: AsyncSession, model, **kwargs):
    stmt = select(model).filter_by(**kwargs)
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj:
        return obj
    obj = model(**kwargs)
    db.add(obj)
    await db.flush()
    return obj


@router.get("/", response_model=MovieListResponseSchema)
async def get_movies(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(func.count(MovieModel.id)))
    total_items = result.scalar_one()

    if total_items == 0:
        raise HTTPException(status_code=404, detail="No movies found.")

    total_pages = ceil(total_items / per_page)
    if page > total_pages:
        raise HTTPException(status_code=404, detail="No movies found.")

    offset = (page - 1) * per_page
    result_movies = await db.execute(
        select(MovieModel)
        .order_by(MovieModel.id.desc())
        .offset(offset)
        .limit(per_page)
    )
    movies = result_movies.scalars().all()

    return {
        "movies": movies,
        "total_pages": total_pages,
        "total_items": total_items,
        "prev_page": (
            f"{BASE_URL}/?page={page - 1}&per_page={per_page}"
            if page > 1 else None
        ),
        "next_page": (
            f"{BASE_URL}/?page={page + 1}&per_page={per_page}"
            if page < total_pages else None
        ),
    }


@router.post(
    "/",
    response_model=MovieDetailSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_movie(
    data: MovieCreateSchema,
    db: AsyncSession = Depends(get_db),
):
    if data.date > date.today() + timedelta(days=365):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid input data.",
        )

    stmt = select(MovieModel).where(
        MovieModel.name == data.name,
        MovieModel.date == data.date,
    )
    existing_movie = (await db.execute(stmt)).scalar_one_or_none()

    if existing_movie:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A movie with the name '{data.name}' and release "
                f"date '{data.date}' already exists."
            ),
        )

    country = await get_or_create(db, CountryModel, code=data.country)

    movie = MovieModel(
        name=data.name,
        date=data.date,
        score=data.score,
        overview=data.overview or "",
        status=data.status,
        budget=data.budget,
        revenue=data.revenue,
        country=country,
    )

    movie.genres = [
        await get_or_create(db, GenreModel, name=g) for g in data.genres
    ]
    movie.actors = [
        await get_or_create(db, ActorModel, name=a) for a in data.actors
    ]
    movie.languages = [
        await get_or_create(db, LanguageModel, name=lang) for lang in data.languages
    ]

    db.add(movie)
    await db.commit()

    final_stmt = (
        select(MovieModel)
        .options(
            selectinload(MovieModel.country),
            selectinload(MovieModel.genres),
            selectinload(MovieModel.actors),
            selectinload(MovieModel.languages)
        )
        .where(MovieModel.id == movie.id)
    )
    result = await db.execute(final_stmt)
    return result.scalar_one()


@router.get("/{movie_id}/", response_model=MovieDetailSchema)
async def get_movie(movie_id: int, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(MovieModel)
        .options(
            selectinload(MovieModel.country),
            selectinload(MovieModel.genres),
            selectinload(MovieModel.actors),
            selectinload(MovieModel.languages)
        )
        .where(MovieModel.id == movie_id)
    )
    movie = (await db.execute(stmt)).scalar_one_or_none()

    if not movie:
        raise HTTPException(
            status_code=404,
            detail="Movie with the given ID was not found."
        )

    return movie


@router.patch("/{movie_id}/", status_code=status.HTTP_200_OK)
async def update_movie(
    movie_id: int,
    data_raw: dict,
    db: AsyncSession = Depends(get_db)
):
    try:
        data = MovieUpdateSchema(**data_raw)
    except (ValidationError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid input data."
        )

    # 2. Пошук фільму в базі
    stmt = (
        select(MovieModel)
        .options(
            selectinload(MovieModel.country),
            selectinload(MovieModel.genres),
            selectinload(MovieModel.actors),
            selectinload(MovieModel.languages)
        )
        .where(MovieModel.id == movie_id)
    )
    result = await db.execute(stmt)
    movie = result.scalar_one_or_none()

    if not movie:
        raise HTTPException(
            status_code=404,
            detail="Movie with the given ID was not found."
        )

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(movie, key, value)

    await db.commit()
    return {"detail": "Movie updated successfully."}


@router.delete("/{movie_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_movie(movie_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(MovieModel).where(MovieModel.id == movie_id)
    movie = (await db.execute(stmt)).scalar_one_or_none()

    if not movie:
        raise HTTPException(
            status_code=404,
            detail="Movie with the given ID was not found."
        )

    await db.delete(movie)
    await db.commit()
    return None
