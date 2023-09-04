#!/usr/bin/env groovy
node {
    checkout scm
    def buildlib = load("pipeline-scripts/buildlib.groovy")
    commonlib = buildlib.commonlib

    commonlib.describeJob("cleanup-locks", """
        ----------
        Cleanup locks
        ----------
        Clean up locks that might stay locked after cancelling jobs by hand.

        Timing: Triggered by jobs on user interruption:
        - ocp4
    """)

    properties(
        [
            disableResume(),
            [
                $class: 'ParametersDefinitionProperty',
                parameterDefinitions: [
                    commonlib.mockParam(),
                    string(
                        name: "LOCKS",
                        description: 'Comma/space-separated list of locks to be removed',
                        trim: true,
                    )
                ]
            ]
        ]
    )

    // Check for mock build
    commonlib.checkMock()

    // Clean up locks
    stage('cleanup-locks') {
        sh "rm -rf ./artcd_working && mkdir -p ./artcd_working"
        def cmd = [
            "artcd",
            "-v",
            "--working-dir=./artcd_working",
            "--config=./config/artcd.toml",
            "cleanup-locks",
            "--locks=${commonlib.cleanCommaList(params.LOCKS)}"
        ]

        withCredentials([
                    string(credentialsId: 'redis-server-password', variable: 'REDIS_SERVER_PASSWORD'),
                    string(credentialsId: 'redis-host', variable: 'REDIS_HOST'),
                    string(credentialsId: 'redis-port', variable: 'REDIS_PORT'),
                ]) {
            sh(script: cmd.join(' '), returnStdout: true)
        }
    }
}
