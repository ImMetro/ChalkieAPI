import json
from flask import Flask, request, jsonify, render_template, make_response
import firebase_admin
from firebase_admin import credentials, auth, firestore
from genericpath import exists


cred_obj = credentials.Certificate('service-account-staging.json')
firebase_admin.initialize_app(cred_obj)
db = firestore.client()
