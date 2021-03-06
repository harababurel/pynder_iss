import itertools
from pprint import pformat

from flask import render_template, redirect, url_for, session, request, flash, jsonify
from flask.views import View, MethodView

from config import config

import repository
from fb_auth import get_access_token
from form_util import SettingsForm
from models import TinderUser, Hopeful, Match, Vote
from statistics import StatisticsGenerator


class ApplicationView():

    @staticmethod
    def logged_in():
        return 'username' in session

    @staticmethod
    def get_pynder_session():
        return repository.RepoUser.load_pynder_session(session['username'])


class IndexView(View, ApplicationView):

    def dispatch_request(self):
        if not self.logged_in():
            return render_template('index.html')
        return redirect(url_for('matches'))


class ChatView(MethodView, ApplicationView):

    def post(self, user_id):
        pynder_session = self.get_pynder_session()
        current_match = None
        for match in list(itertools.islice(
                pynder_session.matches(), 0, config['max_matches_shown'])):
            if match.user.id == user_id:
                current_match = match
                break
        message = request.form['message']

        try:
            print("sending message <%s> to %r." %
                  (message, current_match.user))
            current_match.message(message)
            print("message sent :)")
        except:
            print("could not send message to %r" % current_match.user)

        return ""


class MatchesView(View, ApplicationView):

    def dispatch_request(self):
        if not self.logged_in():
            return render_template('index.html')
        pynder_session = self.get_pynder_session()

        current_matches = list(itertools.islice(
            pynder_session.matches(), 0, config['max_matches_shown']))

        matched_users = [x.user for x in current_matches]

        for user in matched_users:
            if not repository.RepoTinderUser.tinder_user_exists(user):
                print(
                    "TinderUser %r is a previous match and is missing from the db. Adding now." % user)

                try:
                    repository.RepoTinderUser.add_tinder_user(TinderUser(user))
                except Exception as e:
                    print(
                        "Could not add TinderUser %r to the database. Reason: %s" % (user, e))

        return render_template("matches.html",
                               session=session,
                               matched_users=matched_users)


class SwipeView(View, ApplicationView):

    def dispatch_request(self):
        if not self.logged_in():
            return render_template('index.html')
        pynder_session = self.get_pynder_session()
        try:
            current_person = next(pynder_session.nearby_users())
            repository.RepoTinderUser.add_tinder_user(
                TinderUser(current_person))
        except Exception as e:
            return render_template("base.html",
                                   error="No people nearby. %s" % e)
        else:
            hopeful = Hopeful(current_person)
            repository.RepoHopeful.add_hopeful(hopeful)
            return render_template("swipe.html",
                                   session=session,
                                   person=current_person,
                                   person_hash_code=hopeful.hash_code)


class VoteView(MethodView, ApplicationView):

    def post(self):
        if not self.logged_in():
            return render_template('index.html')

        pynder_session = self.get_pynder_session()

        hash_code = int(request.form['person_hash_code'])

        hopeful = repository.RepoHopeful.get_hopeful(hash_code)
        vote = None

        for x in ["dislike", "like", "superlike"]:
            if x in request.form:
                vote = x

        print("voted: %s" % vote)

        if vote is None:
            print("Vote is None")
            return redirect(url_for('index'), error="vote was None")

        if vote == 'dislike':
            hopeful.dislike()
            match = False
        elif vote == 'like':
            match = hopeful.like()
        else:
            match = hopeful.superlike()

        repository.RepoVote.add(Vote(pynder_session.profile, hopeful, vote))

        print("match = %r" % match)

        if match is not False:

            repository.RepoMatch.add(
                Match(pynder_session.profile.id, hopeful.id))

            message = "You have got a new match!"
            if match['is_super_like']:
                message += " %s superliked you :)" % hopeful.name

            flash(message)
            # return render_template('new_match.html', \
            #         person=hopeful, \
            #         match=match)
            return redirect(url_for('swipe'))
        else:
            return redirect(url_for('swipe'))


class StatisticsView(MethodView, ApplicationView):

    def get(self, category):
        if not self.logged_in():
            return render_template('index.html')

        if category == 'general':
            hopefuls = list(repository.RepoHopeful.get_all_hopefuls())
            data = StatisticsGenerator.generate_age_statistics(hopefuls)
            data['category'] = 'general'
        else:
            pynder_session = self.get_pynder_session()
            profile = pynder_session.profile
            data = StatisticsGenerator.generate_vote_statistics(profile)
            data['category'] = 'personal'

        pretty_data = pformat(data, indent=2).replace("\n", "<br>")
        return render_template('statistics.html',
                               data=data,
                               pretty_data=pretty_data)


class LoginView(MethodView, ApplicationView):

    def get(self):
        if self.logged_in():
            return redirect(url_for('index'))
        else:
            return render_template('login.html')

    def post(self):
        try:
            username = request.form['username']
            password = request.form['password']

            access_token = get_access_token(username, password)

            print("access token is %s" % access_token)

            if repository.RepoUser.user_exists(username):
                print("user exists; updating access token")
                repository.RepoUser.update_user(username, access_token)
            else:
                print("user does not exist; creating new")
                repository.RepoUser.add_user(username, access_token)

            session['username'] = username
            # session['access_token'] = access_token

            pynder_session = self.get_pynder_session()
            repository.RepoTinderUser.add_tinder_user(
                TinderUser(pynder_session.profile))

            return redirect(url_for('index'))

        except Exception as e:
            return render_template("base.html",
                                   error="Could not get access token. %s" % e)


class SettingsView(MethodView, ApplicationView):

    def get(self):

        if not self.logged_in():
            return render_template('index.html')

        pynder_session = self.get_pynder_session()

        form = SettingsForm(request.form)

        form.fill_fields_from_profile(pynder_session)

        return render_template("settings.html", session=session, form=form)

    def post(self):

        if not self.logged_in():
            return render_template('index.html')

        pynder_session = self.get_pynder_session()

        form = SettingsForm(request.form)
        # data = dict([(a, getattr(form, a).data) for a in dir(
        #     form) if not a.startswith("__") and hasattr(getattr(form, a), 'data')])
        # pretty_data = pformat(data, indent=2).replace("\n", "<br>")
        # return pretty_data

        form.update_profile_from_fields(pynder_session)

        form.fill_fields_from_profile(pynder_session)

        return render_template("settings.html", session=session, form=form)


class LogoutView(View, ApplicationView):

    def dispatch_request(self):
        if not self.logged_in():
            return render_template('index.html')

        session.pop('username', None)
        # session.pop('access_token', None)
        return redirect(url_for('index'))


class MessagesView(MethodView, ApplicationView):

    def post(self):
        if not self.logged_in():
            return render_template('index.html')

        pynder_session = self.get_pynder_session()
        current_match = None

        for match in list(itertools.islice(
                pynder_session.matches(), 0, config['max_matches_shown'])):

            if match.user.id == request.json['match']:
                current_match = match

            if not repository.RepoTinderUser.tinder_user_exists(match.user):
                print(
                    "TinderUser %r is a previous match and is missing from the db. Adding now." % match.user)

                try:
                    repository.RepoTinderUser.add_tinder_user(
                        TinderUser(match.user))
                except Exception as e:
                    print("Could not add TinderUser %r to the database. Reason: %s" % (
                        match.user, e))

            if not repository.RepoMatch.match_exists(pynder_session.profile.id, match.user.id):
                print("There is no match between %r and %r in the database. Adding now." % (
                    pynder_session.profile.id, match.user.id))

                try:
                    repository.RepoMatch.add(
                        Match(pynder_session.profile.id, match.user.id))
                except Exception as e:
                    print("Could not add match between %r and %r to the database. Reason: %s" % (
                        pynder_session.profile.id, match.user.id, e))

        if current_match is None:
            seen_messages = 0
        else:
            seen_messages = repository.RepoMatch.get_message_count(
                pynder_session.profile.id, current_match.user.id)

        try:
            profile_photo = list(pynder_session.profile.photos)[0]
        except:
            profile_photo = 'static/qms.png'

        message_list = current_match.messages

        if request.json['active']:
            if int(request.json['messageNumber']) == 0:
                repository.RepoMatch.set_message_count(
                    pynder_session.profile.id, current_match.user.id, len(message_list))
                return render_template("messages.html",
                                       messages=message_list,
                                       user=pynder_session.profile,
                                       profile_photo=profile_photo)

            if len(message_list) > seen_messages:
                repository.RepoMatch.set_message_count(
                    pynder_session.profile.id, current_match.user.id, len(message_list))
                message_list = message_list[
                    int(request.json['messageNumber']):]
                return render_template("messages.html",
                                       messages=message_list,
                                       user=pynder_session.profile,
                                       profile_photo=profile_photo)
        else:
            if len(message_list) > seen_messages:
                return jsonify("1")
        return ""


class UnmatchView(MethodView, ApplicationView):

    def post(self, id):
        pynder_session = self.get_pynder_session()
        current_match = None
        for match in list(itertools.islice(
                pynder_session.matches(), 0, config['max_matches_shown'])):
            if match.user.id == id:
                current_match = match
                break

        if current_match is None:
            print("Unable to delete match with id=%r: match not found" % id)
            return ""

        try:
            print("Deleting match %r" % current_match)
            current_match.delete()
            print("Match deleted.")
        except Exception as e:
            print("Could not delete match %r. Reason: %s" % (current_match, e))

        return ""
