import React from 'react';
import { Amplify } from 'aws-amplify';
import { Authenticator } from '@aws-amplify/ui-react';
import '@aws-amplify/ui-react/styles.css';
import { awsConfig } from './aws-config';
import Chat from './Chat';

Amplify.configure(awsConfig);

function App() {
  return (
    <Authenticator
      signUpAttributes={['email']}
      loginMechanisms={['username']}
    >
      {({ signOut, user }) => (
        <Chat user={user} signOut={signOut} />
      )}
    </Authenticator>
  );
}

export default App;