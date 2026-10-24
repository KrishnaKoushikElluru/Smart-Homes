"""migrate listing table to property table

Revision ID: 8a1b2c3d4e5f
Revises: f79c8d82e1d2
"""

from datetime import datetime
import re

from alembic import op
import sqlalchemy as sa


revision = "8a1b2c3d4e5f"

down_revision = "f79c8d82e1d2"

branch_labels = None

depends_on = None


def upgrade():

    # ========================================================
    # 1. CREATE PROPERTY TABLE
    # ========================================================

    op.create_table(

        "property",

        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True
        ),

        sa.Column(
            "seller_id",
            sa.Integer(),
            nullable=False
        ),

        sa.Column(
            "property_type",
            sa.String(50),
            nullable=True
        ),

        sa.Column(
            "listing_type",
            sa.String(20),
            nullable=False
        ),

        sa.Column(
            "price",
            sa.Integer(),
            nullable=False
        ),

        sa.Column(
            "bhk",
            sa.Integer(),
            nullable=True
        ),

        sa.Column(
            "area",
            sa.Float(),
            nullable=True
        ),

        sa.Column(
            "description",
            sa.Text(),
            nullable=True
        ),

        sa.Column(
            "address",
            sa.String(255),
            nullable=True
        ),

        sa.Column(
            "city",
            sa.String(100),
            nullable=True
        ),

        sa.Column(
            "locality",
            sa.String(100),
            nullable=True
        ),

        sa.Column(
            "latitude",
            sa.Float(),
            nullable=True
        ),

        sa.Column(
            "longitude",
            sa.Float(),
            nullable=True
        ),

        sa.Column(
            "amenities",
            sa.Text(),
            nullable=True
        ),

        sa.Column(
            "image_filename",
            sa.String(500),
            nullable=True
        ),

        sa.Column(
            "video_filename",
            sa.String(255),
            nullable=True
        ),

        sa.Column(
            "contact_name",
            sa.String(100),
            nullable=False
        ),

        sa.Column(
            "contact_phone",
            sa.String(20),
            nullable=False
        ),

        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="ACTIVE"
        ),

        sa.Column(
            "source",
            sa.String(50),
            nullable=False,
            server_default="OWNER"
        ),

        sa.Column(
            "source_url",
            sa.String(500),
            nullable=True
        ),

        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False
        ),

        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False
        ),

        sa.ForeignKeyConstraint(
            ["seller_id"],
            ["user.id"]
        )
    )


    # ========================================================
    # 2. GET DATABASE CONNECTION
    # ========================================================

    connection = op.get_bind()


    # ========================================================
    # 3. READ EXISTING LISTINGS
    # ========================================================

    listings = connection.execute(
        sa.text(
            """
            SELECT
                id,
                price,
                contact_name,
                contact_phone,
                video_filename,
                listing_type,
                area,
                specifications,
                username
            FROM listing
            """
        )
    ).fetchall()


    # ========================================================
    # 4. GET USERS
    # ========================================================

    users = connection.execute(
        sa.text(
            """
            SELECT
                id,
                username
            FROM user
            """
        )
    ).fetchall()


    user_map = {
        row.username: row.id
        for row in users
    }


    # ========================================================
    # 5. EXTRACT BHK
    # ========================================================

    def extract_bhk(text):

        if not text:
            return None

        match = re.search(
            r"(\d+)\s*BHK",
            text,
            re.IGNORECASE
        )

        if match:
            return int(
                match.group(1)
            )

        return None


    # ========================================================
    # 6. EXTRACT CITY + LOCALITY
    # ========================================================

    def extract_location(area_text):

        if not area_text:
            return None, None

        parts = [
            part.strip()
            for part in area_text.split(",")
            if part.strip()
        ]

        if not parts:
            return None, None

        city = parts[0]

        locality = None

        if len(parts) >= 2:
            locality = parts[1]

        return city, locality


    # ========================================================
    # 7. MIGRATE EACH LISTING
    # ========================================================

    for listing in listings:

        (
            listing_id,
            price,
            contact_name,
            contact_phone,
            video_filename,
            listing_type,
            old_area,
            specifications,
            username
        ) = listing


        # ----------------------------------------------------
        # Find seller
        # ----------------------------------------------------

        seller_id = user_map.get(
            username
        )

        if seller_id is None:

            raise RuntimeError(
                f"Could not find user "
                f"'{username}' for listing "
                f"{listing_id}."
            )


        # ----------------------------------------------------
        # Extract BHK
        # ----------------------------------------------------

        bhk = extract_bhk(
            specifications
        )


        # ----------------------------------------------------
        # Extract city/locality
        # ----------------------------------------------------

        city, locality = extract_location(
            old_area
        )


        # ----------------------------------------------------
        # Insert migrated property
        # ----------------------------------------------------

        connection.execute(
            sa.text(
                """
                INSERT INTO property (
                    id,
                    seller_id,
                    property_type,
                    listing_type,
                    price,
                    bhk,
                    area,
                    description,
                    address,
                    city,
                    locality,
                    latitude,
                    longitude,
                    amenities,
                    image_filename,
                    video_filename,
                    contact_name,
                    contact_phone,
                    status,
                    source,
                    source_url,
                    created_at,
                    updated_at
                )
                VALUES (
                    :id,
                    :seller_id,
                    :property_type,
                    :listing_type,
                    :price,
                    :bhk,
                    :area,
                    :description,
                    :address,
                    :city,
                    :locality,
                    :latitude,
                    :longitude,
                    :amenities,
                    :image_filename,
                    :video_filename,
                    :contact_name,
                    :contact_phone,
                    :status,
                    :source,
                    :source_url,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": listing_id,

                "seller_id": seller_id,

                "property_type": None,

                "listing_type": listing_type,

                "price": price,

                "bhk": bhk,

                "area": None,

                "description": specifications,

                "address": old_area,

                "city": city,

                "locality": locality,

                "latitude": None,

                "longitude": None,

                "amenities": None,

                "image_filename": None,

                "video_filename": video_filename,

                "contact_name": contact_name,

                "contact_phone": contact_phone,

                "status": "ACTIVE",

                "source": "OWNER",

                "source_url": None,

                "created_at": datetime.utcnow(),

                "updated_at": datetime.utcnow()
            }
        )


def downgrade():

    op.drop_table(
        "property"
    )