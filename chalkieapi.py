from datetime import datetime
from flask import Flask, request, render_template, make_response
import firebase_admin
from firebase_admin import credentials, auth, firestore
from genericpath import exists

cred_obj = credentials.Certificate('service-account-staging.json')
firebase_admin.initialize_app(cred_obj)
db = firestore.client()

app = Flask(__name__)

@app.route('/')
def get_root():
    print('sending root')
    return render_template('index.html')

@app.route('/api/docs')
def get_docs():
    print('sending docs')
    return render_template('swaggerui.html')


# -------------------- ACTUAL API CODE GOES HERE --------------------

# To make another api call, add another @app.route() and define the methods

# Connecting to our firebase using a service account
# /service-account-staging for ChalkieStaging
# /serviceAccount for chalkieApp

@app.route('/api/v1/templates/<string:template_id>/subscribe', methods=['PUT'])
def subscribe(template_id: str): 
    #Document doesn't exist
    info = db.collection('Template').document(template_id).get()
    if not (info.exists):
        return make_response(f'The template id: {template_id} does not exist', 400)

    info = info.to_dict()
    transaction = db.transaction()

    #Get Header
    auth_header = request.headers.get('Authorization')
    if auth_header == []:
        return 'No Authorization Header', 400
    idToken = auth_header.split(' ')[1]

    decoded_token = auth.verify_id_token(idToken)
    uid = decoded_token['uid']

    #Task Calculations of 100
    task_collection = db.collection('Task').where('session_course', '==', info['session_course']).where('user_id', '==', uid).stream()
    count_marks = 0
    for i in task_collection:
        i = i.to_dict()
        count_marks += i['weight']
    count_marks += info['weight']
    
    if count_marks > 100:
        return make_response('Current Tasks exceed total Weighting of 100, please make some changes', 400)

    #Check that the user is not subscribed
    check_subscription = db.collection('Template').document(template_id).collection('Subscribers').where('user_id', '==', uid).get()

    #Is already subscribed
    if len(check_subscription) > 0:
        return make_response('User is already subscribed, Cannot resubscribe', 403)

    #Not Subscirbed and Not the Owner
    elif (len(check_subscription) < 1) and (uid != info['owner']):  
        template_transaction = db.collection('Template').document(template_id)
        get_student_course = db.collection('StudentCourse').where('user_id', '==', uid).where('session_course', '==', info['session_course']).get()
        studentcourse_docname = get_student_course[0].id

        @firestore.transactional
        def update_in_transaction(transaction, template1):

            template_snapshot = template1.get(transaction = transaction)

            #Write new task data
            new_task_data = {
                'template_id': template_id,
                'user_id': uid,
                'deadline': info['deadline'],
                'is_completed': False,
                'is_deleted': False,
                'session_course': info['session_course'],
                'weight': info['weight'],
                'progress': 0,
                'created_at': datetime.now(),
                'need_mark': 0,
                'task_name': info['task_name'],
                'updated_at': datetime.now(),
                'achieved_marks': 0,
                'course': studentcourse_docname
            }

            #upload task data into firestore
            upload_task = db.collection('Task').add(new_task_data)
            upload_task

            #update subsriber number +1 

            transaction.update(template1, {
                'subscriber_no': template_snapshot.get('subscriber_no') + 1
            })

            #insert new document into collection
            user_id = {
                'user_id': uid
            }

            #Add subscriber to collection in Firestore with userid, DocName = user_id
            add_subscriber = db.collection('Template').document(template_id).collection('Subscribers').document(uid).set(user_id)
            print(add_subscriber)

            return True
        
        if (update_in_transaction(transaction, template_transaction)):
            return make_response('Successfully Susbcribed', 200)

    #Not Susbcribed but is Owner of template
    elif (len(check_subscription) < 1) and (uid == info['owner']):  

        #Check Does not have associated Task 
        if info['owner_task'] is not None:
            return make_response('User already has the associated task', 403)
        
        #User Does not have associated Task
        template_db = db.collection('Template').document(f'{template_id}')

        @firestore.transactional
        def update_in_transaction_owner(transaction, template_db):

            #Make stuff for the transaction here
            new_task_data = {
                'template_id': template_id,
                'user_id': uid,
                'deadline': info['deadline'],
                'is_completed': False,
                'is_deleted': False,
                'session_course': info['session_course'],
                'weight': info['weight'],
                'progress': 0,
                'created_at': datetime.now(),
                'need_mark': 0,
                'task_name': info['task_name'],
                'updated_at': datetime.now(),
                'achieved_marks': 0,
                'course': studentcourse_docname
            }

            task_data_upload = db.collection('Task').add(new_task_data)

            transaction.update(template_db, {
                'owner_task': task_data_upload.id
            })
            return True

        if (update_in_transaction_owner(transaction, template_db)):
            return make_response('Successfully Susbcribed', 200)

#Unsubscribe
@app.route('/api/v1/templates/<string:task_id>/unsubscribe', methods=['DELETE'])
def unsubscribe(task_id: str): 
    #Document doesn't exist
    if not (db.collection('Task').document(task_id).get().exists):
        return make_response(f'The task id: {task_id} does not exist', 400)

    info = db.collection('Task').document(task_id).get().to_dict()
    transaction = db.transaction()

    #Get Header
    auth_header = request.headers.get('Authorization')
    if auth_header == []:
        return 'No Authorization Header', 400
    idToken = auth_header.split(' ')[1]

    decoded_token = auth.verify_id_token(idToken)
    uid = decoded_token['uid']

    #Task Does not belong to user
    if info['user_id'] != uid:
        return make_response('Requesting User does not own this task', 400)

    #Fetch Template Data
    template_data = db.collection('Template').document(info['template_id'])

    if (info['template_id'] is None) or not (template_data.exists):
        return make_response("Task was not created from a user subscribing to a template", 403)

    subscriber_list = template_data.collection('Subscribers')

    #Owner Check
    def check_owner():
        check = template_data.get().to_dict()
        if task_id == check['owner_task']:
            return True
        else:
            return False

    if check_owner:
        return make_response("User is owner of the template, cannot unsubscribe", 403)

    @firestore.transactional
    def unsubscribe_transaction(transaction, db):

        db_snapshot = db.get(transaction = transaction)

        #Delete the Task
        db.collection('Task').document(task_id).delete()

        #Remove user from Subscriber List
        subscriber_list.document(uid).delete()

        #Decrease subscriber number by 1
        transaction.update(db, {
            'subscriber_no': db_snapshot.get('subscriber_no') - 1
        })

        return True

    if unsubscribe_transaction(transaction, template_data):
        return make_response('Successfully Unsubsribed', 200)

    else:
        return make_response('Invalid HTTP Method', 400) 

#Get Friend User Data
@app.route('/api/v1/get_friend_user/<string:friend_user_id>', methods=['GET'])
def getFriendData(friend_user_id: str): 
    #Get Header
    auth_header = request.headers.get('Authorization')
    if auth_header == []:
        return make_response('No Authorization Header', 400)
    idToken = auth_header.split(' ')[1]

    decoded_token = auth.verify_id_token(idToken)
    requesting_user = decoded_token['uid']

    #Check if user is an actual friend
    user_db = db.collection('User').where('auth_id', '==', requesting_user).get()
    #Check to see if requested user actually exists
    if len(user_db) < 1:
        return make_response("Requested UserID does not exist", 403)
    user_data = user_db[0].to_dict()
    user_friends = user_data['friend_ids']

    if user_friends != []:
        if friend_user_id in user_friends:
            #Data Collection of Friends Data
            friend_db = db.collection('User').where('auth_id', '==', friend_user_id).get()
            friend_data = friend_db[0].to_dict()

            #Get Friends Courses/Tasks
            course_data = []
            friend_courses = db.collection('StudentCourse').where('user_id', '==', friend_user_id).get()
            if len(friend_courses) > 0:
                for i in friend_courses:
                    course_info = i.to_dict()
                    temp_course_data = [{
                        'course_id': course_info['course_document_id'],
                        'session_id': course_info['session_id'], #This will change in accordance to to the new data structure
                        'course_name': course_info['course_name'],
                        'course_code': course_info['course_id'],
                        'session_year': course_info['year'],
                        'session_name': course_info['session_name']
                    }]
                    course_data += temp_course_data


            return_data = {
                'id': friend_data['auth_id'],
                'name': friend_data['name'],
                'image_url': friend_data['image_url'],
                'courses': course_data,
                'degree': friend_data['degree'],
                'university_name': friend_data['university_name'],
                'university_email': friend_data['university_email']
            }

            return make_response(return_data, 200)

    return make_response("Requested Friend Data is not a friend of the user - Access Denied", 403)

@app.route('/api/v1/query_user/<string:query_string>', methods=['GET'])
def query_user(query_string: str): 
    #Get Header
    auth_header = request.headers.get('Authorization')
    if auth_header == []:
        return make_response('No Authorization Header', 400)
    idToken = auth_header.split(' ')[1]

    decoded_token = auth.verify_id_token(idToken)
    uid = decoded_token['uid']

    return 200


app.run(use_reloader=True, debug=False)
