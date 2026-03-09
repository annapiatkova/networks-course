from flask import Flask, request, jsonify, send_from_directory
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)

products = [
	{ "id": 1, "name": "apples", "image_filename": "apples.jpg" },
]

IMAGE_FOLDER = os.path.join(os.getcwd(), 'images')
app.config['UPLOAD_FOLDER'] = IMAGE_FOLDER
ALLOWED_EXTENSIONS = { 'png', 'jpg', 'jpeg' }

def allowed_file(filename):
	return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def _find_next_id():
    return max(p["id"] for p in products) + 1

@app.get("/products")
def get_all_products():
	return jsonify(products)

@app.get("/products/<int:product_id>")
def get_product_by_id(product_id):
	return [p for p in products if p["id"] == product_id]

@app.post("/products")
def add_product():
	if request.is_json:
		product = request.get_json()
		product["id"] = _find_next_id()
		products.append(product)
		return product, 201
	return {"error": "Request must be JSON"}, 415

@app.put("/products/<int:product_id>")
def update_product(product_id):
	if request.is_json:
		for i in range(len(products)):
			if products[i]["id"] == product_id:
				new_product = request.get_json()
				products[i].update(new_product)
				return products[i], 201
		return {"error": "Product not found"}, 422
	return {"error": "Request must be JSON"}, 415

@app.delete("/products/<int:product_id>")
def delete_product(product_id):
	for i in range(len(products)):
		if products[i]["id"] == product_id:
			del products[i]
			return {}, 204
	return {"error": "Product not found"}, 422

@app.post("/products/<int:product_id>/image")
def upload_image(product_id):
	if 'icon' not in request.files:
		return {"error": "Invalid request: no file"}, 415
	file = request.files['icon']
	if file.filename == '':
		return {"error": "Invalid request: no filename"}, 415
	if file and allowed_file(file.filename):
		for i in range(len(products)):
			if products[i]["id"] == product_id:
				filename = secure_filename(file.filename)
				file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
				products[i]["image_filename"] = filename
				return send_from_directory(IMAGE_FOLDER, products[i]["image_filename"], as_attachment=True)
		return {"error": "Product not found"}, 422


@app.get("/products/<int:product_id>/image")
def get_image(product_id):
	for i in range(len(products)):
		if products[i]["id"] == product_id:
			return send_from_directory(IMAGE_FOLDER, products[i]["image_filename"], as_attachment=True)
	return {"error": "Product not found"}, 422