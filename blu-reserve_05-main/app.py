from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_pymongo import PyMongo
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv
import os
from flask_cors import CORS
import qrcode
from io import BytesIO
import base64

load_dotenv()

app = Flask(__name__, static_folder="app/static", template_folder="app/templates")
app.secret_key = os.getenv("SECRET_KEY")  # Required for session to work
CORS(app)
app.config["MONGO_URI"] = os.getenv("MONGO_URI")
mongo = PyMongo(app)

client = MongoClient(app.config["MONGO_URI"])
db = client["Seat_Reservation_System"]
Employee = db["Employee"]
BluFunds = db["BluFunds"]
SeatMap = db["SeatMap"]
Reservation = db["Reservation"]
Employee_credentials = db["Employee_credentials"]

@app.route("/", methods=["PUT", "GET"])
def homepage():
    return render_template("login.html")

@app.route('/dashboard', defaults={'emp_id': None})
@app.route("/dashboard/<emp_id>", methods=["GET"])
def dashboard(emp_id):
    # First, check if the user is logged in by verifying session['emp_id']
    if 'emp_id' not in session:
        return redirect(url_for('homepage'))  # Redirect to login if not logged in
    
    # If the emp_id from the URL is provided, ensure it's the same as the session emp_id
    if emp_id and int(emp_id) != session['emp_id']:
        return redirect(url_for('homepage'))  # Redirect if emp_id doesn't match the session's emp_id
    
    return render_template("dashboard.html", emp_id=int(session['emp_id']))  # Use emp_id from session

@app.route("/reserve", methods=["GET"])
def reserve():
    if 'emp_id' not in session:
        return redirect(url_for('homepage'))  # Ensure the user is logged in
    return render_template("reserve.html", emp_id=int(session['emp_id']))

@app.route('/seat_map/<emp_id>')
def seat_map(emp_id):
    date = request.args.get('date')
    time = request.args.get('time')
    num_slots = int(request.args.get('num_slots'))

    return render_template('seat_map.html', 
                           emp_id=emp_id,
                           date=date,
                           time=time,
                           num_slots=num_slots)

@app.route("/employee/is_manager", methods=["GET"])
def is_manager():
    emp_id = request.args.get("emp_id")
    employee = BluFunds.find_one({"emp_id": int(emp_id)})
    if employee:
        return jsonify({"is_manager": True}), 200
    return jsonify({"is_manager": False}), 200

@app.route("/confirmation/<emp_id>/<reservation_id>", methods=["GET"])
def confirmation(emp_id, reservation_id):
    if 'emp_id' not in session or session['emp_id'] != int(emp_id):  # Check if emp_id in session matches the URL
        return redirect(url_for('homepage'))  # Redirect to login if emp_id doesn't match
    return render_template("confirmation.html", emp_id=int(emp_id), reservation_id=(reservation_id))

@app.route("/manager/<emp_id>")
def manager_dashboard(emp_id):
    if 'emp_id' not in session or session['emp_id'] != int(emp_id):  # Check if emp_id in session matches the URL
        return redirect(url_for('homepage'))  # Redirect to login if emp_id doesn't match

    return render_template("manager_dashboard.html", emp_id = int(emp_id))

@app.route("/employee/verification", methods=["PUT", "GET"])
def verify_employee():
    data = request.json
    username = data.get("username")
    password = data.get("password")
    employee = Employee_credentials.find_one({"username": username, "password": password})
    if employee:
        session.clear()
        emp_id = employee['emp_id']
        session['emp_id'] = emp_id  # Store emp_id in session
        return jsonify({"status": True, "emp_id": emp_id}), 200
    return jsonify({"status": False}), 200

@app.route("/seats/available", methods=["GET"])
def get_available_seats():
    date = request.args.get("date")
    time = request.args.get("time")
    num_slots = int(request.args.get("number_of_slots"))

    available_seats = [i for i in range(1, 101)]
    reserved_seats = []
    reservation_ids = []
    for reservation in Reservation.find():
        if reservation['date'] == date:
            if reservation['time'] == time:
                reservation_ids.append(reservation['reservation_id'])
            else:
                reserved_time = reservation["time"]
                reserved_slots = reservation['num_slots']
                if int(reserved_time.split(':')[0]) + int(reserved_slots) > int(time.split(':')[0]):
                    if int(reserved_time.split(':')[0]) < int(time.split(':')[0]):
                        reservation_ids.append(reservation['reservation_id'])
                    else:
                        if int(reserved_time.split(':')[0]) < int(time.split(':')[0]) + int(num_slots):
                            reservation_ids.append(reservation['reservation_id'])

    for seat in SeatMap.find():
        for reservation_id in reservation_ids:
            if seat['reservation_id'] == reservation_id:
                reserved_seats.append(seat['seat_id'])
    for i in reserved_seats:
         available_seats.remove(i)

    return available_seats, 200

@app.route("/seats/reservation/<int:emp_id>", methods=["POST"])
def reserve_seat(emp_id):
    # Check if emp_id from session matches the one from the URL
    if 'emp_id' not in session or session['emp_id'] != emp_id:
        return jsonify({"status": False, "message": "Unauthorized: emp_id mismatch"}), 401
    
    # Debug: Log the incoming data
    data = request.json
    print(f"Received reservation request for emp_id: {emp_id}")
    print(f"Data received: {data}")

    seat_ids = data.get("seat_ids")
    date = data.get("date")
    time = data.get("time")
    number_of_slots = int(data.get("number_of_slots"))

    if not seat_ids or not date or not time or not number_of_slots:
        return jsonify({"status": False, "message": "Missing required fields"}), 400

    # Generate a reservation ID
    reservation_id = int(''.join(date.split('-')) + ''.join(time.split(':')) + ''.join(seat_ids))

    try:
        # Insert reservation into DB
        Reservation.insert_one({
            "emp_id": emp_id,
            "reservation_id": reservation_id,
            "time": time,
            "num_slots": number_of_slots,
            "date": date
        })

        # Update BluFunds
        manager = Employee.find_one({"emp_id": emp_id})
        if not manager:
            return jsonify({"status": False, "message": "Employee not found"}), 404

        manager_id = manager.get("manager_id")
        BluFunds.update_one({"emp_id": int(manager_id)},
                            {"$inc": {"funds_outstanding": 100 * number_of_slots * len(seat_ids)}})

        # Insert seat data into SeatMap
        seat_data = [{"seat_id": int(i), "reservation_id": int(reservation_id)} for i in seat_ids]
        SeatMap.insert_many(seat_data)

        return jsonify({"status": True, "reservation_id": str(reservation_id)}), 201
    except Exception as e:
        print(f"Error during reservation: {e}")
        return jsonify({"status": False, "message": "Error during reservation"}), 500

@app.route("/seats/cancellation", methods=["PUT"])
def cancel_reservation():
    reservation_id = request.json.get("reservation_id")
    reservation = Reservation.find_one({"reservation_id": int(reservation_id)})
    
    if not reservation or reservation["emp_id"] != session.get("emp_id"):  # Check if emp_id in session matches reservation emp_id
        return jsonify({"status": False, "message": "Unauthorized access"}), 401

    seats = []
    for seat in SeatMap.find():
        if seat['reservation_id'] == int(reservation_id):
            seats.append(int(seat['seat_id']))
    
    manager = Employee.find_one({"emp_id": int(session['emp_id'])})
    manager_id = manager.get("manager_id")
    amount = int(reservation["num_slots"]) * 100 * len(seats)
    funds = BluFunds.find_one({"emp_id": int(manager_id)})
    
    if funds:
        BluFunds.update_one(
            {"emp_id": manager_id},
            {"$inc": {"funds_outstanding": -amount}}
        )

    Reservation.delete_one({"_id": reservation["_id"]})
    SeatMap.delete_many({"reservation_id": int(reservation_id)})
    return jsonify({"status": True}), 200

@app.route("/seats/reservation/", methods=["GET"])
def get_employee_reservations():
    emp_id = request.args.get("emp_id")
    
    if 'emp_id' not in session or session['emp_id'] != int(emp_id):  # Check if emp_id in session matches the query parameter
        return jsonify({"status": False, "message": "Unauthorized access"}), 401
    
    reservations = Reservation.find({"emp_id": int(emp_id)})
    reservation_list = [{"id": str(res["_id"]), "emp_id": res["emp_id"], "date": res["date"], "time": res["time"], "Number_of_slots": res["num_slots"], "reservation_id": str(res["reservation_id"])} for res in reservations]
    return jsonify(reservation_list), 200

@app.route("/manager/blufunds", methods=["GET"])
def get_blu_funds():
    emp_id = request.args.get("emp_id")
    funds = BluFunds.find_one({"emp_id": int(emp_id)})
    if funds:
        return jsonify({
            "current_funds": funds.get("curr_funds"),
            "funds_outstanding": funds.get("funds_outstanding")
        }), 200
    else:
        return jsonify({"status": "No funds found"}), 404

@app.route("/manager/fund_updation", methods=["PUT"])
def update_funds():
    data = request.json
    emp_id = data.get("emp_id")
    amount = data.get("amount")

    funds = BluFunds.find_one({"emp_id": int(emp_id)})
    if funds:
        updated_funds = funds["curr_funds"] + int(amount)
        BluFunds.update_one(
            {"emp_id": int(emp_id)},
            {"$set": {"curr_funds": updated_funds}}
        )
        return jsonify({"status": True}), 200
    else:
        return jsonify({"status": False}), 400
    

@app.route("/reservation/details/<reservation_id>", methods=["GET"])
def get_reservation_details(reservation_id):
    reservation = Reservation.find_one({"reservation_id": int(reservation_id)})

    if not reservation or reservation["emp_id"] != session.get("emp_id"):  # Check if emp_id in session matches reservation emp_id
        return jsonify({"status": "Unauthorized access"}), 401

    emp_id = reservation.get("emp_id")
    date = reservation.get("date")
    time = reservation.get("time")
    num_slots = reservation.get("num_slots")
    seat_ids = SeatMap.find({"reservation_id": int(reservation_id)})
    seat_list = [seat['seat_id'] for seat in seat_ids]

    # Generate a QR code for the reservation ID
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(int(reservation_id))
    qr.make(fit=True)

    # Create an image from the QR code
    img = qr.make_image(fill='black', back_color='white')

    # Convert the image to a base64 string
    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr = img_byte_arr.getvalue()
    qr_code_base64 = base64.b64encode(img_byte_arr).decode('utf-8')

    return jsonify({
        "reservation_id": reservation_id,
        "emp_id": emp_id,
        "date": date,
        "time": time,
        "num_slots": num_slots,
        "seats": seat_list,
        "qr_code_url": f"data:image/png;base64,{qr_code_base64}"
    }), 200

if __name__ == "__main__":
    app.run(debug=True)