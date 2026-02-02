from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from database import get_db
from database.models import CountryModel, GenreModel, ActorModel, LanguageModel, MovieModel
from schemas.movies import MovieListResponseSchema, MovieCreateSchema, MovieDetailResponseSchema, MovieUpdateSchema

router = APIRouter()


@router.get("/movies/", response_model=MovieListResponseSchema)
async def get_movies(
        db: AsyncSession = Depends(get_db),
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=10, ge=1, le=20)):
    total_count_query = await db.execute(select(func.count(MovieModel.id)))
    total_items = total_count_query.scalar() or 0
    if total_items == 0:
        raise HTTPException(status_code=404, detail="No movies found.")

    total_pages = (total_items + per_page - 1) // per_page
    offset = (page - 1) * per_page

    if offset >= total_items:
        raise HTTPException(status_code=404, detail="No movies found.")

    query = select(MovieModel).order_by(MovieModel.id.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    movies = result.scalars().all()

    base_path = "/api/v1/theater/movies/"

    prev_page = f"{base_path}?page={page - 1}&per_page={per_page}" if page > 1 else None
    next_page = f"{base_path}?page={page + 1}&per_page={per_page}" if page < total_pages else None

    if not movies:
        raise HTTPException(status_code=404, detail="No movies found.")

    return {
        "movies": movies,
        "prev_page": prev_page,
        "next_page": next_page,
        "total_pages": total_pages,
        "total_items": total_items,
    }


async def get_or_create(db: AsyncSession, model, field, value, **kwargs):
    instance = await db.execute(select(model).where(getattr(model, field) == value))
    instance = instance.scalar_one_or_none()

    if not instance:
        instance = model(**{field: value}, **kwargs)
        db.add(instance)

    return instance


@router.post("/movies/", response_model=MovieDetailResponseSchema, status_code=201)
async def create_movie(movie: MovieCreateSchema, db: AsyncSession = Depends(get_db)):
    existing_movie = await db.execute(select(MovieModel).where(
        MovieModel.name == movie.name,
        MovieModel.date == movie.date
    ))
    if existing_movie.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"A movie with the name '{movie.name}' and "
                   f"release date '{movie.date}' already exists."
        )

    try:
        country = await get_or_create(db, CountryModel, "code", movie.country)
        data = movie.model_dump(exclude={"genres", "actors", "languages", "country"})
        new_movie = MovieModel(**data, country=country)

        for genre_name in movie.genres:
            genre_obj = await get_or_create(db, GenreModel, "name", genre_name)
            new_movie.genres.append(genre_obj)

        for actor_name in movie.actors:
            actor_obj = await get_or_create(db, ActorModel, "name", actor_name)
            new_movie.actors.append(actor_obj)

        for language_name in movie.languages:
            language_obj = await get_or_create(db, LanguageModel, "name", language_name)
            new_movie.languages.append(language_obj)

        db.add(new_movie)
        await db.commit()

        result = await db.execute(
            select(MovieModel)
            .options(joinedload(MovieModel.country), joinedload(MovieModel.genres),
                     joinedload(MovieModel.actors), joinedload(MovieModel.languages))
            .where(MovieModel.id == new_movie.id)
        )
        return result.unique().scalar_one()

    except Exception:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid input data.")


@router.get("/movies/{movie_id}/", response_model=MovieDetailResponseSchema)
async def get_movie_detail(movie_id: int, db: AsyncSession = Depends(get_db)):
    query = (
        select(MovieModel)
        .options(
            joinedload(MovieModel.country),
            joinedload(MovieModel.genres),
            joinedload(MovieModel.actors),
            joinedload(MovieModel.languages)
        )
        .where(MovieModel.id == movie_id)
    )

    result = await db.execute(query)
    movie = result.unique().scalar_one_or_none()

    if not movie:
        raise HTTPException(status_code=404, detail="Movie with the given ID was not found.")

    return movie


@router.delete("/movies/{movie_id}/", status_code=204)
async def delete_movie(movie_id: int, db: AsyncSession = Depends(get_db)):
    movie = await db.get(MovieModel, movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="Movie with the given ID was not found.")

    await db.delete(movie)
    await db.commit()
    return None


@router.patch("/movies/{movie_id}/")
async def update_movie(movie_id: int, movie: MovieUpdateSchema, db: AsyncSession = Depends(get_db)):
    db_movie = await db.get(MovieModel, movie_id)
    if not db_movie:
        raise HTTPException(status_code=404, detail="Movie with the given ID was not found.")

    update_data = movie.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="Invalid input data.")

    for key, value in update_data.items():
        setattr(db_movie, key, value)

    try:
        await db.commit()
        return {"detail": "Movie updated successfully."}
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid input data.")
