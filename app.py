from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from pymongo import MongoClient
import os
from werkzeug.utils import secure_filename
import google.generativeai as genai
from geopy.distance import geodesic
from PIL import Image
import io
import base64
import re
#flask code

app = Flask(__name__)
app.secret_key = os.urandom(24) 

# MongoDB Connection
client = MongoClient("mongodb://localhost:27017/")
db = client["zomatoDB"]
collection = db["details"]

# Configure Gemini API (Replace with your actual API key)
genai.configure(api_key="AIzaSyC2tISJZZZ5FJnJ5w5oSnywPan6EBiIJHY")

# Upload Folder Configuration
UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}

def allowed_file(filename):
    """Check if uploaded file has a valid image extension."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def detect_cuisine(image):
    """Detect cuisine from an uploaded image using Gemini API."""
    model = genai.GenerativeModel("gemini-1.5-flash")

    # Convert image to base64
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format="JPEG")
    img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")

    # Request Gemini API to detect cuisine
    response = model.generate_content([{
        "text": "Identify only the name of the cuisine in one or two words, e.g., 'Italian', 'Indian', 'Mexican', 'Desserts', 'Ice Cream'."
    }, {
        "mime_type": "image/jpeg", "data": img_base64
    }])

    if hasattr(response, "text"):
        cuisine_detected = response.text.strip()

        # Extract only the first cuisine word using regex
        match = re.search(r"\b([A-Za-z\s]+)\b", cuisine_detected)
        if match:
            cuisine_cleaned = match.group(1).strip()
            print(f"✅ Extracted Cuisine: {cuisine_cleaned}")
            return cuisine_cleaned

    return "Unknown"


def get_all_restaurants():
    """Fetch all restaurants from the MongoDB collection."""
    return list(collection.find({}, {"restaurant": 1, "_id": 0}))


def get_city_coordinates(city_name):
    """Fetch latitude & longitude of a given city from MongoDB."""
    city_data = collection.find_one({"restaurant.location.city": {"$regex": f"^{city_name}$", "$options": "i"}})
    if city_data:
        try:
            lat = float(city_data["restaurant"]["location"]["latitude"])
            lon = float(city_data["restaurant"]["location"]["longitude"])
            return lat, lon
        except (TypeError, ValueError, KeyError):
            return None
    return None


def get_nearest_restaurants(latitude, longitude, limit=9):
    """Find restaurants closest to the given latitude & longitude."""
    restaurants = list(collection.find())
    nearest_restaurants = []

    for restaurant in restaurants:
        try:
            rest_lat = float(restaurant["restaurant"]["location"]["latitude"])
            rest_lon = float(restaurant["restaurant"]["location"]["longitude"])
            distance = geodesic((latitude, longitude), (rest_lat, rest_lon)).km
            restaurant["distance"] = distance
            nearest_restaurants.append(restaurant)
        except (TypeError, ValueError, KeyError):
            continue

    sorted_restaurants = sorted(nearest_restaurants, key=lambda x: x["distance"])
    return sorted_restaurants[:limit]


@app.route("/")
def index():
    search_query = request.args.get("search", "").strip().lower()
    city_query = request.args.get("city", "").strip().lower()
    page = int(request.args.get("page", 1))
    per_page = 9  # Updated to show 9 restaurants per page

    if city_query:
        coordinates = get_city_coordinates(city_query)
        if coordinates:
            latitude, longitude = coordinates
            restaurants = get_nearest_restaurants(latitude, longitude, limit=9)
            return render_template("index.html", restaurants=restaurants, page=1, total=len(restaurants), search_query=search_query, city_query=city_query)
        else:
            return render_template("index.html", restaurants=[], page=1, total=0, search_query=search_query, city_query=city_query, message="City not found")

    restaurants = get_all_restaurants()

    if search_query:
        restaurants = [r for r in restaurants if search_query in r["restaurant"]["name"].lower() or search_query in r["restaurant"]["cuisines"].lower()]

    total = len(restaurants)
    paginated = restaurants[(page - 1) * per_page: page * per_page]

    return render_template("index.html", restaurants=paginated, page=page, total=total, search_query=search_query, city_query=city_query)
@app.route("/restaurant/<res_id>")
def restaurant_detail(res_id):
    """Show details of a specific restaurant."""
    restaurants = get_all_restaurants()
    selected = None
    for r in restaurants:
        rid = str(r["restaurant"].get("R", {}).get("res_id", r["restaurant"].get("id", "")))
        if rid == res_id:
            selected = r["restaurant"]
            break

    if not selected:
        return "Restaurant not found", 404

    return render_template("info.html", restaurant=selected)


@app.route("/upload", methods=["GET", "POST"])
def upload_file():
    """Upload image and search for restaurants offering detected cuisine with pagination."""
    if request.method == "POST":
        if "file" not in request.files:
            return "No file uploaded."

        file = request.files["file"]
        if file.filename == "" or not allowed_file(file.filename):
            return "Invalid file format. Please upload a valid image."

        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(file_path)

        image = Image.open(file_path)
        detected_cuisine = detect_cuisine(image)

        # Save detected cuisine in session (so it can be used in GET requests)
        session["detected_cuisine"] = detected_cuisine
    else:
        detected_cuisine = session.get("detected_cuisine", "")

    # Fetch paginated restaurants
    page = int(request.args.get("page", 1))
    per_page = 8
    all_restaurants = list(collection.find({"restaurant.cuisines": {"$regex": detected_cuisine, "$options": "i"}}))
    total = len(all_restaurants)
    paginated_restaurants = all_restaurants[(page - 1) * per_page: page * per_page]

    return render_template(
        "index.html",
        restaurants=paginated_restaurants,
        page=page,
        total=total,
        per_page=per_page,
        search_query=detected_cuisine,
        city_query=""
    )


if __name__ == "__main__":
    app.run(debug=True)
